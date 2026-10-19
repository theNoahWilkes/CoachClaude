#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = [
#   "mpyq>=0.2.5",
#   "six>=1.14",
#   "heroprotocol @ git+https://github.com/Blizzard/heroprotocol",
# ]
# ///
"""hotscoach - rule-based post-game coach for Heroes of the Storm replays.

First run:
  hotscoach.py setup        finds your replays, detects your name, writes config

Usage:
  hotscoach.py analyze REPLAY [--json]
  hotscoach.py batch [DIR] [--new-only]
  hotscoach.py trend [--last N] [--hero HERO]
  hotscoach.py timeline REPLAY
  hotscoach.py positions REPLAY --start M:SS --end M:SS
  (any command accepts --player NAME to override the configured player)

Dependencies: pip install -r requirements.txt  (or run with `uv run`, which reads the
header above). Config: ~/.config/hotscoach/config.json. Env vars HOTS_PLAYER,
HOTS_REPLAY_DIR, HEROPROTOCOL_PATH and HOTSCOACH_DB override it.
"""
import argparse, glob, hashlib, importlib.util, json, math, os, re, sqlite3, sys
from collections import Counter
from collections import defaultdict

# ---------------------------------------------------------------- tunables
TANK_FAR = 30          # units: "your frontline was far away"
ISOLATED = 20          # units: no ally within this = isolated
POS_LOOKBACK = 20      # seconds of position history to trust before a death
FIGHT_GAP = 20         # seconds between deaths that still counts as one fight
PRE_OBJ_WINDOW = 45    # seconds before an objective event
LOOPS_PER_SEC = 16

TANKS = {"anubarak", "arthas", "blaze", "cho", "diablo", "etc", "garrosh", "johanna",
         "malganis", "mei", "muradin", "stitches", "tyrael", "mal'ganis"}
BRUISERS = {"artanis", "chen", "dva", "deathwing", "dehaka", "gazlowe", "hogger",
            "imperius", "leoric", "malthael", "ragnaros", "rexxar", "sonya", "thrall",
            "varian", "xul", "yrel"}
OBJECTIVE_RE = re.compile(r"DragonKnightActivated|Altar Captured|Shrine Captured|"
                          r"SoulEatersSpawned|NukesSpawned|Tribute|RavenCurse|Immortal|"
                          r"GardenTerror|SkyTempleActivated|HauntedMinesGolemsSpawned|Doubloon|BraxisWave|BraxisHoldoutMapEventComplete|Payload|Beacon|CapturePointComplete")
CARRY_DROP_RE = re.compile(r"Dropped")   # e.g. WarheadJunctionNukeDropped
ARAM_MAPS = {"Silver City", "Industrial District", "Braxis Outpost", "Lost Cavern"}  # excluded from trend by default


def norm(name):
    return re.sub(r"[^a-z]", "", name.lower())


# ---------------------------------------------------------------- protocol
_PROTO_CACHE = {}


def _versions_dir():
    """Find heroprotocol's protocol modules: $HEROPROTOCOL_PATH clone, else pip install."""
    base = os.environ.get("HEROPROTOCOL_PATH")
    if base:
        base = os.path.expanduser(base)
        sys.path.insert(0, base)
        return os.path.join(base, "heroprotocol", "versions")
    spec = importlib.util.find_spec("heroprotocol")
    if spec and spec.origin:
        return os.path.join(os.path.dirname(spec.origin), "versions")
    clone = os.path.expanduser("~/src/heroprotocol")
    if os.path.isdir(clone):
        sys.path.insert(0, clone)
        return os.path.join(clone, "heroprotocol", "versions")
    sys.exit("heroprotocol not found: run `pip install -r requirements.txt` "
             "(or `uv run hotscoach.py ...`)")


def load_protocol(build=None):
    """Load a protocol module directly, bypassing heroprotocol's broken (imp-based) loader."""
    if build in _PROTO_CACHE:
        return _PROTO_CACHE[build]
    vdir = _versions_dir()
    builds = sorted(int(m.group(1)) for f in os.listdir(vdir)
                    if (m := re.match(r"protocol(\d+)\.py$", f)))
    if not builds:
        sys.exit(f"no protocol modules in {vdir}")
    pick = build if build in builds else builds[-1]
    if build is not None and pick != build:
        print(f"note: no protocol for build {build}, using {pick} (usually fine)",
              file=sys.stderr)
    name = f"protocol{pick}"
    spec = importlib.util.spec_from_file_location(name, os.path.join(vdir, name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _PROTO_CACHE[build] = mod
    return mod


# ---------------------------------------------------------------- config
CONFIG_PATH = os.path.expanduser("~/.config/hotscoach/config.json")
DATA_DIR = os.path.expanduser("~/.local/share/hotscoach")


def load_config():
    try:
        with open(CONFIG_PATH) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def configured(key, env):
    return os.environ.get(env) or load_config().get(key)


def candidate_replay_roots():
    """Where HotS keeps replays on each platform (Accounts folder; searched recursively)."""
    h = os.path.expanduser("~")
    tail = os.path.join("Documents", "Heroes of the Storm", "Accounts")
    pats = [
        os.path.join(h, tail),                                              # Windows
        os.path.join(h, "OneDrive", tail),                                  # Windows + OneDrive
        os.path.join(h, "Library", "Application Support", "Blizzard",
                     "Heroes of the Storm", "Accounts"),                    # macOS
        os.path.join(h, ".wine*", "drive_c", "users", "*", tail),           # Wine
        os.path.join(h, "Games", "*", "drive_c", "users", "*", tail),       # Lutris
        os.path.join(h, ".local", "share", "Steam", "steamapps", "compatdata", "*",
                     "pfx", "drive_c", "users", "*", tail),                 # Proton
        os.path.join(h, ".steam", "steam", "steamapps", "compatdata", "*",
                     "pfx", "drive_c", "users", "*", tail),
        os.path.join(h, ".var", "app", "com.usebottles.bottles", "data", "bottles",
                     "bottles", "*", "drive_c", "users", "*", tail),        # Bottles
        os.path.join("/mnt", "c", "Users", "*", tail),                      # WSL
    ]
    found = []
    for p in pats:
        for d in glob.glob(p):
            if os.path.isdir(d) and d not in found:
                found.append(d)
    return found


def find_replays(root):
    return sorted(glob.glob(os.path.join(root, "**", "*.StormReplay"), recursive=True),
                  key=os.path.getmtime)


def replay_names(path):
    import mpyq
    archive = mpyq.MPQArchive(path)
    header = load_protocol().decode_replay_header(archive.header["user_data_header"]["content"])
    proto = load_protocol(header["m_version"]["m_baseBuild"])
    det = proto.decode_replay_details(archive.read_file("replay.details"))
    return [p["m_name"].decode() for p in det["m_playerList"]]


def read_replay(path):
    import mpyq
    archive = mpyq.MPQArchive(path)
    contents = archive.header["user_data_header"]["content"]
    # header format is stable across builds; read it with the newest protocol
    header = load_protocol().decode_replay_header(contents)
    proto = load_protocol(header["m_version"]["m_baseBuild"])
    details = proto.decode_replay_details(archive.read_file("replay.details"))
    tracker = list(proto.decode_replay_tracker_events(archive.read_file("replay.tracker.events")))
    return details, tracker


# ---------------------------------------------------------------- helpers
def ints(e, key):
    return [d["m_value"] for d in (e.get("m_intData") or []) if d["m_key"] == key]


def fixed(e, key):
    return [d["m_value"] / 4096 for d in (e.get("m_fixedData") or []) if d["m_key"] == key]


class Game:
    def __init__(self, path, player):
        details, tr = read_replay(path)
        self.path = path
        self.map = details["m_title"].decode()
        self.players = []
        for i, p in enumerate(details["m_playerList"]):
            self.players.append(dict(pid=i + 1, name=p["m_name"].decode(),
                                     hero=p["m_hero"].decode(), team=p["m_teamId"],
                                     win=p["m_result"] == 1))
        me = [p for p in self.players if p["name"].lower() == player.lower()]
        if not me:
            sys.exit(f"{player!r} not in replay: {[p['name'] for p in self.players]}")
        self.me = me[0]
        self.pid = {p["pid"]: p for p in self.players}

        stats = [e for e in tr if e["_event"].endswith("SStatGameEvent")]
        gates = [e["_gameloop"] for e in stats if e["m_eventName"] == b"GatesOpen"]
        self.loop0 = gates[0] if gates else 610
        self.length = (max(e["_gameloop"] for e in tr) - self.loop0) / LOOPS_PER_SEC

        # map midline from structure positions (team sides)
        towns = [(fixed(e, b"PositionX")[0], ints(e, b"Team")[0] if ints(e, b"Team") else None)
                 for e in stats if e["m_eventName"] == b"TownStructureInit" and fixed(e, b"PositionX")]
        xs = [x for x, _ in towns]
        self.mid_x = (min(xs) + max(xs)) / 2 if xs else None
        # does my team own the low-x side?
        left_team = 0
        my_side = [x for x, t in towns if t == self.me["team"] + 1]
        if my_side and self.mid_x is not None:
            left_team = self.me["team"] if sum(my_side) / len(my_side) < self.mid_x else 1 - self.me["team"]
        self.left_team = left_team

        self.deaths, self.objectives, self.drops, self.xp = [], [], [], {}
        self.camps, self.structures, self.levels = [], [], {}
        town_team = {ints(e, b"TownID")[0]: ints(e, b"Team")[0] - 1 for e in stats
                     if e["m_eventName"] == b"TownStructureInit" and ints(e, b"TownID") and ints(e, b"Team")}
        for e in stats:
            n = e["m_eventName"].decode()
            t = self.sec(e["_gameloop"])
            if n == "PlayerDeath":
                self.deaths.append(dict(t=t, victim=ints(e, b"PlayerID")[0],
                                        killers=[k for k in ints(e, b"KillingPlayer") if k],
                                        x=fixed(e, b"PositionX")[0], y=fixed(e, b"PositionY")[0]))
            elif OBJECTIVE_RE.search(n):
                self.objectives.append((t, n))
            elif CARRY_DROP_RE.search(n):
                self.drops.append(t)
            elif n == "JungleCampCapture":
                team = fixed(e, b"TeamID")
                camp = e["m_stringData"][0]["m_value"].decode() if e.get("m_stringData") else "camp"
                self.camps.append((t, camp, int(team[0]) - 1 if team else None))
            elif n == "TownStructureDeath":
                town = ints(e, b"TownID")
                kind = e["m_stringData"][0]["m_value"].decode() if e.get("m_stringData") else "structure"
                self.structures.append((t, kind, town_team.get(town[0]) if town else None))
            elif n == "LevelUp":
                pid, lvl = ints(e, b"PlayerID")[0], ints(e, b"Level")[0]
                if pid in self.pid:
                    self.levels.setdefault((self.pid[pid]["team"], lvl), t)
            elif n == "PeriodicXPBreakdown":
                team = ints(e, b"Team")[0] - 1   # 1/2 -> 0/1
                xp = {d["m_key"].decode(): d["m_value"] / 4096 for d in e["m_fixedData"]}
                self.xp.setdefault(round(t / 60), {})[team] = xp

        # hero positions (sampled; only heroes recently in combat appear)
        tag2pid = {}
        for e in tr:
            if e["_event"].endswith("SUnitBornEvent") and e["m_unitTypeName"].startswith(b"Hero"):
                pid = e["m_controlPlayerId"]
                if pid in self.pid and pid not in tag2pid.values():
                    tag2pid[e["m_unitTagIndex"]] = pid
        self.positions = []  # (t, pid, x, y)
        for e in tr:
            if e["_event"].endswith("SUnitPositionsEvent"):
                ui, it = e["m_firstUnitIndex"], e["m_items"]
                for i in range(0, len(it), 3):
                    ui += it[i]
                    if ui in tag2pid:
                        self.positions.append((self.sec(e["_gameloop"]), tag2pid[ui], it[i + 1], it[i + 2]))

        self.score = {}
        for e in tr:
            if e["_event"].endswith("SScoreResultEvent"):
                for inst in e["m_instanceList"]:
                    vals = [v[0]["m_value"] if v else 0 for v in inst["m_values"]]
                    self.score[inst["m_name"].decode()] = vals

    def sec(self, loop):
        return (loop - self.loop0) / LOOPS_PER_SEC

    def stat(self, key, pid=None):
        vals = self.score.get(key)
        return vals[(pid or self.me["pid"]) - 1] if vals else None

    def last_pos(self, pid, t):
        best = None
        for pt, p, x, y in self.positions:
            if p == pid and t - POS_LOOKBACK <= pt <= t:
                best = (x, y)
        return best

    def near_pos(self, pid, t, window=POS_LOOKBACK):
        cands = [(abs(pt - t), (x, y)) for pt, p, x, y in self.positions
                 if p == pid and abs(pt - t) <= window]
        return min(cands)[1] if cands else None

    def allies(self):
        return [p for p in self.players if p["team"] == self.me["team"] and p is not self.me]

    def frontline(self):
        al = self.allies()
        tanks = [p for p in al if norm(p["hero"]) in TANKS]
        return tanks or [p for p in al if norm(p["hero"]) in BRUISERS]


def fmt(t):
    return f"{int(t // 60)}:{int(t % 60):02d}"


# ---------------------------------------------------------------- analysis
def analyze(g):
    me = g.me
    my_pid = me["pid"]
    enemy_deaths = [d for d in g.deaths if g.pid[d["victim"]]["team"] != me["team"]]
    takedowns = [d for d in enemy_deaths if my_pid in d["killers"]]

    # cluster deaths into fights
    fights, cur = [], []
    for d in sorted(g.deaths, key=lambda d: d["t"]):
        if cur and (d["t"] - cur[-1]["t"] > FIGHT_GAP or
                    math.dist((d["x"], d["y"]), (cur[-1]["x"], cur[-1]["y"])) > 45):
            fights.append(cur); cur = []
        cur.append(d)
    if cur: fights.append(cur)

    front = g.frontline()
    death_reports = []
    for d in [d for d in g.deaths if d["victim"] == my_pid]:
        flags = []
        fight = next(f for f in fights if d in f)
        ours = [x for x in fight if g.pid[x["victim"]]["team"] == me["team"]]
        theirs = [x for x in fight if g.pid[x["victim"]]["team"] != me["team"]]
        if len(fight) == 1:
            flags.append("picked off (no other deaths in this fight)")
        elif ours[0] is d:
            flags.append(f"first of your team to die (fight: you lost {len(ours)}, they lost {len(theirs)})")
        if len(d["killers"]) >= 3:
            flags.append(f"collapsed on by {len(d['killers'])}")
        if g.mid_x is not None:
            on_left = d["x"] < g.mid_x
            if on_left != (me["team"] == g.left_team) and abs(d["x"] - g.mid_x) > 8:
                flags.append("died on the enemy half of the map")
        mypos = g.last_pos(my_pid, d["t"])
        if mypos:
            ally_d = [(math.dist(mypos, pp), p["hero"]) for p in g.allies()
                      if (pp := g.last_pos(p["pid"], d["t"]))]
            if ally_d and min(ally_d)[0] > ISOLATED:
                flags.append(f"isolated (nearest ally {min(ally_d)[0]:.0f} units)")
            for p in front:
                pp = g.last_pos(p["pid"], d["t"])
                if pp and math.dist(mypos, pp) > TANK_FAR:
                    flags.append(f"{p['hero']} was {math.dist(mypos, pp):.0f} units away")
            if front and not any(g.last_pos(p["pid"], d["t"]) for p in front):
                flags.append("frontline not seen in combat in the 20s before")
        nxt = [o for o in g.objectives if 0 <= o[0] - d["t"] <= PRE_OBJ_WINDOW]
        if nxt:
            flags.append(f"died {nxt[0][0] - d['t']:.0f}s before objective ({nxt[0][1]})")
        if any(abs(t - d["t"]) <= 2 for t in g.drops):
            flags.append("dropped a carried objective item")
        killers = ", ".join(g.pid[k]["hero"] for k in d["killers"]) or "NPC/structure"
        death_reports.append(dict(t=fmt(d["t"]), killers=killers, flags=flags))

    # fights your team lost while you were alive and elsewhere
    absent = []
    for f in fights:
        ours = [x for x in f if g.pid[x["victim"]]["team"] == me["team"]]
        if len(ours) < 2 or any(x["victim"] == my_pid for x in f):
            continue
        cx = sum(x["x"] for x in ours) / len(ours); cy = sum(x["y"] for x in ours) / len(ours)
        mypos = g.near_pos(my_pid, ours[-1]["t"])
        if mypos and math.dist(mypos, (cx, cy)) > 40:
            absent.append(f"{fmt(ours[0]['t'])}: lost {len(ours)} while you were {math.dist(mypos, (cx, cy)):.0f} units away")

    # XP: where did the gap come from?
    xp_notes = []
    for minute in (6, 10):
        snap = g.xp.get(minute, {})
        if len(snap) == 2:
            mine, theirs = snap[me["team"]], snap[1 - me["team"]]
            tot = lambda d: sum(v for k, v in d.items() if k.endswith("XP"))
            gap = tot(theirs) - tot(mine)
            if gap > 0.12 * tot(mine):
                parts = {k: theirs[k] - mine[k] for k in ("MinionXP", "HeroXP", "StructureXP", "CreepXP") if k in mine}
                biggest = max(parts, key=parts.get)
                xp_notes.append(f"{minute}:00 behind {gap:,.0f} XP, mostly {biggest} (+{parts[biggest]:,.0f} for them)")

    # recurring killer
    kc = defaultdict(int)
    for d in g.deaths:
        if d["victim"] == my_pid:
            for k in d["killers"]: kc[g.pid[k]["hero"]] += 1
    my_deaths = len(death_reports)
    nemesis = [h for h, c in kc.items() if my_deaths >= 3 and c >= max(3, my_deaths - 1)]

    healing = g.stat("Healing") or 0
    tf_heal = g.stat("TeamfightHealingDone") or 0
    dead = g.stat("TimeSpentDead") or 0
    m = dict(
        player=me["name"], map=g.map, hero=me["hero"], win=me["win"], length=round(g.length),
        deaths=my_deaths, time_dead=dead, pct_dead=round(100 * dead / max(g.length, 1), 1),
        kp=round(100 * len(takedowns) / max(len(enemy_deaths), 1)),
        healing=healing, teamfight_healing=tf_heal,
        tf_heal_pct=round(100 * tf_heal / healing) if healing else None,
        hero_damage=g.stat("HeroDamage"), damage_taken=g.stat("DamageTaken"),
        clutch_heals=g.stat("ClutchHealsPerformed"), xp=g.stat("ExperienceContribution"),
        first_deaths=sum("first of your team" in f for r in death_reports for f in r["flags"]),
        picked_off=sum("picked off" in f for r in death_reports for f in r["flags"]),
        enemy_half=sum("enemy half" in f for r in death_reports for f in r["flags"]),
        far_from_front=sum(any("units away" in f for f in r["flags"]) for r in death_reports),
    )

    # coaching notes
    notes = []
    if m["pct_dead"] >= 20:
        notes.append(f"Dead {m['pct_dead']}% of the game. Survival is the priority next game.")
    if m["far_from_front"] >= 2:
        notes.append("Multiple deaths with your frontline far away - stand behind your tank.")
    if m["first_deaths"] >= 2:
        notes.append("First to die in several fights - hold position a step further back.")
    if m["enemy_half"] >= 2:
        notes.append("Several deaths on the enemy half - let the tank lead pushes.")
    if m["picked_off"] >= 1:
        notes.append("Picked off alone at least once - rotate with teammates.")
    if nemesis:
        notes.append(f"Recurring killer: {', '.join(nemesis)}. Plan around them before the next fight.")
    if healing and m["tf_heal_pct"] is not None and m["tf_heal_pct"] < 15:
        notes.append(f"Only {m['tf_heal_pct']}% of healing in teamfights - check you're in Chain Heal range when fights start.")
    pre_obj = sum(any("before objective" in f for f in r["flags"]) for r in death_reports)
    if pre_obj >= 2:
        notes.append(f"{pre_obj} deaths shortly before objectives - play safe as objectives approach.")
    for a_ in absent:
        notes.append(f"Absent from a lost fight - {a_}.")
    for x_ in xp_notes:
        notes.append(f"XP: {x_}.")
    m["absent_fights"] = len(absent)
    if not notes:
        notes.append("No rule flags tripped. Clean game by these metrics.")
    return m, death_reports, notes


# ---------------------------------------------------------------- storage
def db():
    path = os.environ.get("HOTSCOACH_DB", os.path.join(DATA_DIR, "games.db"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE IF NOT EXISTS games (id TEXT PRIMARY KEY, played TEXT, file TEXT, metrics TEXT)")
    return con


def replay_id(path):
    with open(path, "rb") as f:
        return hashlib.sha1(f.read()).hexdigest()[:16]


def save(con, path, m):
    played = os.path.basename(path)[:17]
    con.execute("INSERT OR REPLACE INTO games VALUES (?,?,?,?)",
                (replay_id(path), played, os.path.basename(path), json.dumps(m)))
    con.commit()


# ---------------------------------------------------------------- output
def print_report(m, deaths, notes):
    res = "WIN" if m["win"] else "LOSS"
    print(f"\n== {m['map']} - {m['hero']} - {res} ({fmt(m['length'])}) ==")
    line = f"deaths {m['deaths']}  dead {fmt(m['time_dead'])} ({m['pct_dead']}%)  KP {m['kp']}%"
    if m["healing"]:
        line += f"  healing {m['healing']:,} (teamfight {m['tf_heal_pct']}%)  clutch {m['clutch_heals']}"
    print(line)
    for d in deaths:
        print(f"  {d['t']:>6}  <- {d['killers']}")
        for f in d["flags"]:
            print(f"          - {f}")
    print("coach:")
    for n in notes:
        print(f"  * {n}")


def cmd_analyze(a):
    g = Game(a.replay, a.player)
    m, deaths, notes = analyze(g)
    save(db(), a.replay, m)
    if a.json:
        print(json.dumps(dict(metrics=m, deaths=deaths, notes=notes,
                              teams={p["hero"]: ("ally" if p["team"] == g.me["team"] else "enemy")
                                     for p in g.players},
                              objectives=[(fmt(t), n) for t, n in g.objectives]), indent=1))
    else:
        print_report(m, deaths, notes)


def cmd_batch(a):
    con = db()
    seen = {r[0] for r in con.execute("SELECT id FROM games")}
    root = a.dir or configured("replay_dir", "HOTS_REPLAY_DIR")
    if not root:
        sys.exit("no replay folder: pass DIR or run `hotscoach.py setup`")
    files = find_replays(root)
    for f in files:
        if a.new_only and replay_id(f) in seen:
            continue
        try:
            g = Game(f, a.player)
        except SystemExit as e:
            print(f"skip {os.path.basename(f)}: {e}", file=sys.stderr); continue
        m, deaths, notes = analyze(g)
        save(con, f, m)
        print_report(m, deaths, notes)


def cmd_trend(a):
    rows = db().execute("SELECT played, metrics FROM games ORDER BY played").fetchall()
    ms = [json.loads(r[1]) for r in rows]
    if not a.aram:
        ms = [m for m in ms if m["map"] not in ARAM_MAPS]
    if a.hero:
        ms = [m for m in ms if norm(m["hero"]) == norm(a.hero)]
    ms = ms[-a.last:]
    if not ms:
        sys.exit("no games logged yet")
    print(f"{'map':22} {'hero':10} {'res':4} {'D':>2} {'dead%':>6} {'KP%':>4} {'heal':>7} {'tf%':>4} {'1st':>3} {'far':>3}")
    for m in ms:
        print(f"{m['map'][:22]:22} {m['hero'][:10]:10} {'W' if m['win'] else 'L':4} {m['deaths']:>2} "
              f"{m['pct_dead']:>6} {m['kp']:>4} {m['healing'] or 0:>7} {m['tf_heal_pct'] or '-':>4} "
              f"{m['first_deaths']:>3} {m['far_from_front']:>3}")
    avg = lambda k: sum(m[k] or 0 for m in ms) / len(ms)
    wins = sum(m["win"] for m in ms)
    print(f"\n{len(ms)} games, {wins}-{len(ms) - wins}. avg deaths {avg('deaths'):.1f}, "
          f"avg dead {avg('pct_dead'):.1f}%, avg KP {avg('kp'):.0f}%")


def side_label(g, x):
    if g.mid_x is None:
        return ""
    mine_left = g.me["team"] == g.left_team
    return "your half" if (x < g.mid_x) == mine_left else "enemy half"


def cmd_timeline(a):
    g = Game(a.replay, a.player)
    mt = g.me["team"]
    who = lambda p: ("YOU " if p is g.me else "") + p["hero"]
    print(f"== {g.map} ({fmt(g.length)}) - {'WIN' if g.me['win'] else 'LOSS'} ==")
    for label, team in (("allies", mt), ("enemies", 1 - mt)):
        hs = [who(p) + (" [front]" if norm(p["hero"]) in TANKS | BRUISERS else "")
              for p in g.players if p["team"] == team]
        print(f"{label:8}: {', '.join(hs)}")
    print("\nlevel milestones (you / them, delta):")
    for lvl in (4, 7, 10, 13, 16, 20):
        u, t_ = g.levels.get((mt, lvl)), g.levels.get((1 - mt, lvl))
        if u or t_:
            d = f"{u - t_:+.0f}s" if u and t_ else ""
            print(f"  {lvl:>2}: {fmt(u) if u else '-':>6} / {fmt(t_) if t_ else '-':>6}  {d}")
    print("\nXP by source every 2 min (yours/theirs):")
    for minute in sorted(g.xp):
        snap = g.xp[minute]
        if minute % 2 == 0 and len(snap) == 2:
            parts = [f"{k[:-2]} {snap[mt][k]:,.0f}/{snap[1 - mt][k]:,.0f}"
                     for k in ("MinionXP", "HeroXP", "StructureXP", "CreepXP") if k in snap[mt]]
            print(f"  {minute:>2}:00  " + "  ".join(parts))
    events = []
    for d in g.deaths:
        v = g.pid[d["victim"]]
        tag = "ALLY DIED " if v["team"] == mt else "ENEMY DIED"
        killers = ", ".join(g.pid[k]["hero"] for k in d["killers"]) or "NPC"
        events.append((d["t"], f"{tag} {who(v):14} <- {killers}  ({d['x']:.0f},{d['y']:.0f} {side_label(g, d['x'])})"))
    for t, n in g.objectives:
        events.append((t, f"OBJECTIVE  {n}"))
    for t, camp, team in g.camps:
        events.append((t, f"CAMP       {camp} -> {'us' if team == mt else 'them'}"))
    for t, kind, team in g.structures:
        events.append((t, f"STRUCTURE  {kind} lost by {'us' if team == mt else 'them'}"))
    for t in g.drops:
        events.append((t, "DROP       carried item dropped"))
    print("\ntimeline:")
    for t, line in sorted(events):
        print(f"  {fmt(t):>6}  {line}")


def parse_t(s_):
    m_, s2 = s_.split(":")
    return int(m_) * 60 + int(s2)


def cmd_positions(a):
    g = Game(a.replay, a.player)
    lo, hi = parse_t(a.start), parse_t(a.end)
    snaps = defaultdict(dict)
    for t, pid, x, y in g.positions:
        if lo <= t <= hi:
            snaps[t][pid] = (x, y)
    print("sampled ~every 15s; only heroes recently in combat appear. * you, + ally, - enemy, [n] distance from you")
    print("map midline x =", f"{g.mid_x:.0f}" if g.mid_x else "?")
    for t in sorted(snaps):
        s_ = snaps[t]
        me = s_.get(g.me["pid"])
        cells = []
        for p in g.players:
            if p["pid"] in s_:
                x, y = s_[p["pid"]]
                tag = "*" if p is g.me else ("+" if p["team"] == g.me["team"] else "-")
                dist = f"[{math.dist(me, (x, y)):.0f}]" if me and p is not g.me else ""
                cells.append(f"{tag}{p['hero'][:8]}({x},{y}){dist}")
        print(f"{fmt(t):>6} " + " ".join(cells))


def cmd_setup(a):
    print("hotscoach setup\n")
    # 1. dependencies
    try:
        import mpyq  # noqa: F401
        load_protocol()
        print("  [ok] dependencies (mpyq, heroprotocol)")
    except (ImportError, SystemExit) as e:
        sys.exit(f"  [!!] missing dependencies: {e}\n"
                 "       run: pip install -r requirements.txt   (or use `uv run`)")
    cfg = load_config()

    # 2. replay folder
    root = a.replay_dir or os.environ.get("HOTS_REPLAY_DIR") or cfg.get("replay_dir")
    if not root:
        found = [d for d in candidate_replay_roots() if find_replays(d)]
        if not found:
            sys.exit("  [!!] couldn't find a Heroes of the Storm replay folder.\n"
                     "       Play a game first, or pass --replay-dir PATH "
                     "(the folder containing your .StormReplay files).")
        if len(found) > 1:
            for i, d in enumerate(found):
                print(f"       {i + 1}) {d}")
            root = found[int(input("  which replay folder? ") or 1) - 1]
        else:
            root = found[0]
    replays = find_replays(root)
    print(f"  [ok] replays: {root} ({len(replays)} found)")

    # 3. player name: the one name present in all of your recent replays
    player = a.player or os.environ.get("HOTS_PLAYER") or cfg.get("player")
    if not player:
        recent = replays[-15:]
        counts = Counter(n for f in recent for n in set(replay_names(f)))
        top = [n for n, c in counts.most_common() if c == counts.most_common(1)[0][1]]
        if len(recent) >= 3 and len(top) == 1:
            player = top[0]
            print(f"  [ok] player: {player} (in all {counts[player]} recent replays)")
        else:
            if top:
                print(f"       candidates: {', '.join(top)}")
            player = input("  your in-game name: ").strip()
    else:
        print(f"  [ok] player: {player}")

    # 4. save config + lessons file
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    cfg.update(player=player, replay_dir=root)
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)
    print(f"  [ok] config: {CONFIG_PATH}")
    os.makedirs(DATA_DIR, exist_ok=True)
    lessons = os.path.join(DATA_DIR, f"lessons-{player}.md")
    if not os.path.exists(lessons):
        tmpl = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                            "references", "lessons-template.md")
        text = open(tmpl).read() if os.path.exists(tmpl) else "# Lessons: <player>\n"
        with open(lessons, "w") as f:
            f.write(text.replace("<player>", player))
    print(f"  [ok] lessons: {lessons}")
    print("\nDone. Try: hotscoach.py batch --new-only   or, in Claude Code: coach my last game")


def main():
    ap = argparse.ArgumentParser(description="Rule-based HotS replay coach")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("analyze"); p.add_argument("replay"); p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_analyze)
    p = sub.add_parser("batch"); p.add_argument("dir", nargs="?"); p.add_argument("--new-only", action="store_true")
    p.set_defaults(fn=cmd_batch)
    p = sub.add_parser("timeline"); p.add_argument("replay"); p.set_defaults(fn=cmd_timeline)
    p = sub.add_parser("positions"); p.add_argument("replay")
    p.add_argument("--start", required=True); p.add_argument("--end", required=True)
    p.set_defaults(fn=cmd_positions)
    p = sub.add_parser("setup"); p.add_argument("--player"); p.add_argument("--replay-dir")
    p.set_defaults(fn=cmd_setup)
    p = sub.add_parser("trend"); p.add_argument("--last", type=int, default=20); p.add_argument("--hero")
    p.add_argument("--aram", action="store_true", help="include ARAM maps")
    p.set_defaults(fn=cmd_trend)
    for name in ("analyze", "batch", "timeline", "positions"):
        sub.choices[name].add_argument("--player", default=configured("player", "HOTS_PLAYER"))
    a = ap.parse_args()
    if a.cmd in ("analyze", "batch", "timeline", "positions") and not a.player:
        sys.exit("no player configured: run `hotscoach.py setup` (or pass --player)")
    a.fn(a)


if __name__ == "__main__":
    main()
