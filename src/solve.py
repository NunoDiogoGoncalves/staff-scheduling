from __future__ import annotations

import sys
import os
from pathlib import Path
from pyomo.environ import SolverFactory, value
from io_utils import load_data
from model import build_model            # must be the mixed version: build_model(data, flex)
from flexible_candidates import build_flexible_candidates

INTERVAL_HOURS = 0.5  # keep consistent with loader/model/candidates

# ---------- Path handling ----------
def resolve_data_dir(cli_arg: str | None) -> Path:
    """
    Resolve the dataset directory robustly whether we run from root or from src/.
    Default = ../data/miniweek relative to this file.
    """
    here = Path(__file__).resolve()
    default_dir = (here.parent / "../data/miniweek").resolve()
    if cli_arg:
        return (here.parent / cli_arg).resolve() if not Path(cli_arg).is_absolute() else Path(cli_arg)
    return default_dir

# ---------- Sanity helpers ----------
def sanity_check(data: dict):
    required = ["employees","jobs","days","intervals","shifts",
                "wage","skills","availability","jobs_of","covers",
                "pref_kdt","min_kdt"]
    missing = [k for k in required if k not in data]
    if missing:
        raise ValueError(f"load_data() missing keys: {missing}")

    if not data["employees"]: raise ValueError("No employees loaded")
    if not data["jobs"]: raise ValueError("No jobs loaded")
    if not data["days"]: raise ValueError("No days loaded")
    if not data["intervals"]: raise ValueError("No intervals loaded")
    if not data["shifts"]: raise ValueError("No shifts loaded")
    if not data["covers"]:
        raise ValueError("covers (shift coverage) is empty")

    if not data["availability"]:
        print("WARNING: availability dict is empty; using default=0 in model")

def objective_breakdown(m):
    wage_ft = sum(
        value(m.cost[i]) * (value(m.Lj[j]) - value(m.Bj[j])) * value(m.x[i, j, d]) * INTERVAL_HOURS
        for (i, j, d) in m.X
    )
    wage_pt = 0.0
    if len(m.Y) > 0:
        wage_pt = sum(value(m.costP[p]) * value(m.y[p]) for p in m.Y)

    pen_min  = sum(value(m.pen_min)  * value(m.slack_min[k, d, t])  for k in m.K for d in m.D for t in m.T)
    pen_pref = sum(value(m.pen_pref) * value(m.slack_pref[k, d, t]) for k in m.K for d in m.D for t in m.T)

    total = wage_ft + wage_pt + pen_min + pen_pref
    print("\n--- Objective breakdown ---")
    print(f"Wage (FT):   {wage_ft:,.2f}")
    print(f"Wage (PT):   {wage_pt:,.2f}")
    print(f"Penalty min: {pen_min:,.2f}")
    print(f"Penalty pref:{pen_pref:,.2f}")
    print(f"TOTAL:       {total:,.2f}\n")

def export_ft_assignments(m, out_path: Path):
    rows = []
    for (i, j, d) in m.X:
        if value(m.x[i, j, d]) > 0.5:
            rows.append((str(i), str(j), int(d)))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        f.write("employee,shift,day\n")
        for i, j, d in rows:
            f.write(f"{i},{j},{d}\n")
    print(f"Wrote {out_path}")

def export_pt_assignments(m, out_path: Path):
    rows = []
    if len(m.Y) > 0:
        for p in m.Y:
            if value(m.y[p]) > 0.5:
                rows.append((
                    str(value(m.P_i[p])),
                    str(value(m.P_k[p])),
                    int(value(m.P_d[p])),
                    int(value(m.P_s[p])),
                    int(value(m.P_L[p])),
                ))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        f.write("employee,job,day,start_t,length\n")
        for i,k,d,s,L in rows:
            f.write(f"{i},{k},{d},{s},{L}\n")
    print(f"Wrote {out_path}")

def export_all_assignments(m, data, out_path: Path):
    """
    Writes a single CSV merging FT (x) and PT (y) decisions.
    Columns: employee,source,shift_id,job,day,start_t,length,unpaid_breaks
    """
    rows = []

    # ---- FT assignments ----
    # Need start time from the loader data
    start_j = data.get("start_j", {})
    for (i, j, d) in m.X:
        if value(m.x[i, j, d]) > 0.5:
            job = str(value(m.job_of[j]))
            start_t = start_j.get(str(j), start_j.get(j, ""))  # handle str/int keys
            length = int(value(m.Lj[j]))
            unpaid = int(value(m.Bj[j]))
            rows.append((
                str(i), "FT", str(j), job, int(d),
                "" if start_t == "" else int(start_t),
                length, unpaid
            ))

    # ---- PT assignments ----
    if len(m.Y) > 0:
        for p in m.Y:
            if value(m.y[p]) > 0.5:
                i = str(value(m.P_i[p]))
                job = str(value(m.P_k[p]))
                d = int(value(m.P_d[p]))
                s = int(value(m.P_s[p]))
                L = int(value(m.P_L[p]))
                rows.append((i, "PT", "", job, d, s, L, 0))

    # write
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        f.write("employee,source,shift_id,job,day,start_t,length,unpaid_breaks\n")
        for r in rows:
            f.write(",".join(map(str, r)) + "\n")
    print(f"Wrote {out_path}")

def compute_assigned(m, k, d, t) -> float:
    # FT contribution
    assigned = sum(
        value(m.covers[j, t]) * value(m.x[i, j, dd])
        for (i, j, dd) in m.X
        if dd == d and value(m.job_of[j]) == k
    )
    # PT contribution
    if len(m.Y) > 0:
        assigned += sum(
            value(m.covP[p, t]) * value(m.y[p])
            for p in m.Y
            if int(value(m.P_d[p])) == d and value(m.P_k[p]) == k
        )
    return assigned

def export_shortfalls(m, out_path: Path):
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        f.write("job,day,interval,assigned,min_req,pref_req,slack_min,slack_pref\n")
        for k in m.K:
            for d in m.D:
                for t in m.T:
                    assigned = compute_assigned(m, k, d, t)
                    f.write(
                        f"{k},{d},{t},"
                        f"{int(round(assigned))},"
                        f"{int(value(m.minReq[k,d,t]))},"
                        f"{int(value(m.prefReq[k,d,t]))},"
                        f"{int(value(m.slack_min[k,d,t]))},"
                        f"{int(value(m.slack_pref[k,d,t]))}\n"
                    )
    print(f"Wrote {out_path}")

def export_hotspots(m, out_path: Path, top_n: int = 50):
    hotspots = []
    for k in m.K:
        for d in m.D:
            for t in m.T:
                smin = int(value(m.slack_min[k, d, t]))
                if smin > 0:
                    assigned = int(round(compute_assigned(m, k, d, t)))
                    hotspots.append((str(k), int(d), int(t), smin, assigned, int(value(m.minReq[k,d,t]))))
    hotspots.sort(key=lambda r: (-r[3], r[1], r[2]))  # by missing desc, then day, then t

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        f.write("job,day,interval,slack_min,assigned,min_req\n")
        for row in hotspots:
            f.write(",".join(map(str, row)) + "\n")
    print(f"Wrote {out_path}")

    print("\nTop unmet MIN intervals (hotspots):")
    for row in hotspots[:top_n]:
        k,d,t,smin,assigned,minreq = row
        print(f"  {k} d{d} t{t}: missing {smin} (assigned {assigned} vs min {minreq})")
    print()

# ---------- Main ----------
def main():
    # dataset path (CLI arg optional)
    cli_arg = sys.argv[1] if len(sys.argv) >= 2 else None
    data_dir = resolve_data_dir(cli_arg)
    print(f"Using dataset: {data_dir}")

    # 1) Load data (includes blocked → derived availability)
    data = load_data(str(data_dir))

    # 2) Build PT flexible patterns from blocked availability
    flex = build_flexible_candidates(
        data,
        allowed_lengths=(6, 8, 10),  # 3h, 4h, 5h (for 30-min intervals)
        start_window=None            # or (start_index_min, start_index_max)
    )

    # 3) Quick sanity checks
    sanity_check(data)

    # 4) Build mixed model (FT + PT)
    m = build_model(data, flex)

    # 5) Solve
    # Choose your solver: "cbc", "glpk", "gurobi", "cplex", etc.
    solver_name = os.environ.get("SOLVER", "cbc")
    opt = SolverFactory(solver_name)
    # Some CBC builds accept these; ignore if unrecognized
    try:
        opt.options["ratioGap"] = 0.02  # 2% MIP gap
        opt.options["seconds"] = 60     # time limit
    except Exception:
        pass

    results = opt.solve(m, tee=True)
    # Optional: m.pprint()  # if you want to inspect

    # 6) Exports
    data_root = data_dir.parent if (data_dir.name.lower() == "miniweek") else data_dir
    export_ft_assignments(m, data_root / "solution_assignments_ft.csv")
    export_pt_assignments(m, data_root / "solution_assignments_pt.csv")
    export_all_assignments(m, data, data_root / "solution_assignments_all.csv") 
    export_shortfalls(m, data_root / "shortfalls.csv")
    export_hotspots(m, data_root / "hotspots.csv")

    # 7) Objective breakdown
    objective_breakdown(m)

if __name__ == "__main__":
    main()