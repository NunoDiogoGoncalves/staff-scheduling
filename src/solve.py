from pyomo.environ import SolverFactory
from pyomo.environ import value
from io_utils import load_data
from model import build_model

data = load_data("data")

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
asgn = []
for i in m.I:
    for j in m.J:
        for d in m.D:
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
                assigned = sum(value(m.covers[j, t]) * value(m.x[i, j, d])
                               for i in m.I for j in m.J if value(m.job_of[j]) == k)
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
    from pyomo.environ import value
    INTERVAL_HOURS = 0.5
    wage_cost = sum(value(m.cost[i]) * (value(m.Lj[j]) - value(m.Bj[j])) * value(m.x[i, j, d]) * INTERVAL_HOURS
                    for i in m.I for j in m.J for d in m.D)
    pref_pen = value(m.pen_pref) * sum(value(m.slack_pref[k, d, t]) for k in m.K for d in m.D for t in m.T)
    min_pen  = value(m.pen_min)  * sum(value(m.slack_min[k, d, t])  for k in m.K for d in m.D for t in m.T)
    total    = wage_cost + pref_pen + min_pen
    print(f"\nObjective breakdown:")
    print(f"  Wage cost      = {wage_cost:.2f}")
    print(f"  Preferred pen  = {pref_pen:.2f}")
    print(f"  Minimum pen    = {min_pen:.2f}")
    print(f"  TOTAL objective= {total:.2f}\n")

    # Build a list of (k,d,t, slack_min, assigned, min_req)
    hotspots = []
    for k in m.K:
        for d in m.D:
            for t in m.T:
                assigned = sum(value(m.covers[j, t]) * value(m.x[i, j, d])
                            for i in m.I for j in m.J if value(m.job_of[j]) == k)
                smin = value(m.slack_min[k, d, t])
                if smin > 0.0:
                    hotspots.append((
                        str(k), int(d), int(t),
                        int(smin), int(assigned), int(value(m.minReq[k, d, t]))
                    ))

    # Sort by biggest min-slack, then by day, then interval
    hotspots.sort(key=lambda r: (-r[3], r[1], r[2]))

    # Write CSV
    with open("data/hotspots.csv", "w") as f:
        f.write("job,day,interval,slack_min,assigned,min_req\n")
        for k,d,t,smin,assigned,minreq in hotspots:
            f.write(f"{k},{d},{t},{smin},{assigned},{minreq}\n")

    # Quick terminal summary (top 10)
    print("\nTop unmet MIN intervals (hotspots):")
    for row in hotspots[:10]:
        k,d,t,smin,assigned,minreq = row
        print(f"  {k} d{d} t{t}: missing {smin} (assigned {assigned} vs min {minreq})")
    print("Wrote data/hotspots.csv\n")


print_objective_breakdown(m)