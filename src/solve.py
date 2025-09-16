from pyomo.environ import SolverFactory
from pyomo.environ import value
from io_utils import load_data
from model import build_model

data = load_data("data/miniweek")

def debug_data(data):
    print("\n--- SANITY COUNTS ---")
    print("employees:", len(data.get("employees", [])))
    print("jobs:", len(data.get("jobs", [])))
    print("days:", len(data.get("days", [])))
    print("intervals:", len(data.get("intervals", [])))
    print("shifts:", len(data.get("shifts", [])))
    print("availability entries:", len(data.get("availability", {})))
    print("skills employees:", len(data.get("skills", {})))
    print("job_of_j entries:", len(data.get("jobs_of", {})))
    print("covers entries:", len(data.get("covers", {})))

    # sample a few entries
    print("\n--- SAMPLE AVAIL (first 5 where value==1) ---")
    c = 0
    for k,v in data.get("availability", {}).items():
        if v == 1:
            print("avail 1:", k)
            c += 1
            if c >= 5: break

    print("\n--- SAMPLE SKILLS FOR FIRST EMP ---")
    skills_for_i = {k:v for (ii,k),v in data["skills"].items() if ii == "e1"}
    print("e1 skills:", skills_for_i)

    print("\n--- SAMPLE job_of ---")
    for j in data.get("shifts", [])[:5]:
        print(j, "->", data.get("jobs_of", {}).get(j))

#debug_data(data)

def sanity_check(data):
    required = ["employees","jobs","days","intervals","shifts",
                "wage","skills","availability","jobs_of","covers",
                "pref_kdt","min_kdt"]
    missing = [k for k in required if k not in data]
    if missing:
        raise ValueError(f"load_data() missing keys: {missing}")

    if not data["employees"]: raise ValueError("No employees loaded")
    if not data["jobs"]: raise ValueError("No jobs loaded")
    if not data["shifts"]: raise ValueError("No shifts loaded")
    if not data["days"]: raise ValueError("No days loaded")
    if not data["intervals"]: raise ValueError("No intervals loaded")

    # every shift must have a job
    bad = [j for j in data["shifts"] if j not in data["jobs_of"]]
    if bad: raise ValueError(f"Missing jobs_of for shifts: {bad}")

    # covers_jt should have entries for the intervals a shift covers
    # (we allow sparsity; just check it’s not totally empty)
    if not data["covers"]:
        raise ValueError("covers_jt is empty (no shift coverage mapping)")

    # availability should exist (we allow zeros by default in the model)
    if not data["availability"]:
        print("WARNING: availability dict is empty; using default=0 in model")

    # staff targets (preferred/min)
    if not data["pref_kdt"] and not data["min_kdt"]:
        print("WARNING: No staffing targets loaded (pref_kdt/min_kdt empty)")

sanity_check(data)

m = build_model(data)

solver = SolverFactory("cbc")
solver.options["ratioGap"] = 0.02   # stop when within 2% of optimal
solver.options["seconds"] = 60      # time limit
#solver.options["threads"] = 0       # use all cores
result = solver.solve(m, tee=True)


# 1) Write assignments to CSV
# Assignments
asgn = []
for (i, j, d) in m.X:                      # <-- only iterate existing variables
    if value(m.x[i, j, d]) > 0.5:
        asgn.append((i, j, d))

with open("data/solution_assignments.csv", "w") as f:
    f.write("employee,shift,day\n")
    for i, j, d in asgn:
        f.write(f"{i},{j},{d}\n")

print("Wrote data/solution_assignments.csv")

# 2) Write slack / coverage to CSV
with open("data/shortfalls.csv", "w") as f:
    f.write("job,day,interval,assigned,min_req,pref_req,slack_min,slack_pref\n")
    for k in m.K:
        for d in m.D:
            for t in m.T:
                assigned = sum(
                    value(m.covers[j, t]) * value(m.x[i, j, dd])
                    for (i, j, dd) in m.X
                    if dd == d and value(m.job_of[j]) == k
                )
                f.write(
                    f"{k},{d},{t},"
                    f"{int(assigned)},"
                    f"{int(value(m.minReq[k,d,t]))},"
                    f"{int(value(m.prefReq[k,d,t]))},"
                    f"{int(value(m.slack_min[k,d,t]))},"
                    f"{int(value(m.slack_pref[k,d,t]))}\n"
                )
print("Wrote data/shortfalls.csv")

def print_objective_breakdown(m):
    INTERVAL_HOURS = 0.5  # or whatever your interval length is

    wage_cost = sum(
        value(m.cost[i]) * (value(m.Lj[j]) - value(m.Bj[j])) * value(m.x[i, j, d]) * INTERVAL_HOURS
        for (i, j, d) in m.X
    )

    penalty_min = sum(
        value(m.pen_min) * value(m.slack_min[k, d, t])
        for k in m.K for d in m.D for t in m.T
    )

    penalty_pref = sum(
        value(m.pen_pref) * value(m.slack_pref[k, d, t])
        for k in m.K for d in m.D for t in m.T
    )

    print(f"Wage cost: {wage_cost:.2f}")
    print(f"Penalty min: {penalty_min:.2f}")
    print(f"Penalty pref: {penalty_pref:.2f}")
    print(f"Total objective: {wage_cost + penalty_min + penalty_pref:.2f}")


    # Build a list of (k,d,t, slack_min, assigned, min_req)
    hotspots = []
    for k in m.K:
        for d in m.D:
            for t in m.T:
                assigned = sum(
                    value(m.covers[j, t]) * value(m.x[i, j, dd])
                    for (i, j, dd) in m.X
                    if dd == d and value(m.job_of[j]) == k
                )
                smin = int(value(m.slack_min[k, d, t]))
                if smin > 0:
                    hotspots.append((str(k), int(d), int(t), smin, int(assigned), int(value(m.minReq[k,d,t]))))

    hotspots.sort(key=lambda r: (-r[3], r[1], r[2]))

    with open("data/hotspots.csv", "w") as f:
        f.write("job,day,interval,slack_min,assigned,min_req\n")
        for row in hotspots:
            f.write(",".join(map(str, row)) + "\n")

    print("Wrote data/hotspots.csv")

    # Quick terminal summary (top 10)
    print("\nTop unmet MIN intervals (hotspots):")
    for row in hotspots[:10]:
        k,d,t,smin,assigned,minreq = row
        print(f"  {k} d{d} t{t}: missing {smin} (assigned {assigned} vs min {minreq})")
    print("Wrote data/hotspots.csv\n")


print_objective_breakdown(m)