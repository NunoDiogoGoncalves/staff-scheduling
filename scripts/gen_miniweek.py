"""
Generate a small-but-realistic scheduling dataset.

Outputs 5 CSVs (comma-delimited) into the --out folder:
  - employees.csv        employee_id;name;type;hourly_cost
  - skills.csv           employee_id;job
  - shifts.csv           shift_id;day;job,start_t;length;unpaid_breaks_Bj
  - availability.csv     employee_id;day;shift_id,;vailable
  - demand.csv           day;t;job;preferred;min

Conventions (match your loader & model):
  - Time is in discrete "intervals". We default to 30-min slots.
  - length and unpaid are IN INTERVALS (not hours).
  - start_t is the first covered interval for the shift.
  - coverage for a shift j is t ∈ [start_t, start_t+length]  (inclusive)
    If your model uses Python range as range(s, s+L), set length accordingly.
  - availability rows include only entries with value=1 (present).
"""

#!/usr/bin/env python3
import argparse, random, csv
from pathlib import Path

def ensure_dir(p: Path):
    p.mkdir(parents=True, exist_ok=True)

def write_csv_semicolon(path, header, rows):
    with open(path, "w", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(header)
        w.writerows(rows)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="data/miniweek", help="Output folder")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--employees", type=int, default=10)
    parser.add_argument("--intervals_per_day", type=int, default=28)  # e.g. 14..41 if start=14
    parser.add_argument("--start_interval", type=int, default=14)     # first interval id in a day
    args = parser.parse_args()

    random.seed(args.seed)
    out_dir = Path(args.out)
    ensure_dir(out_dir)

    # ---------------- Sets / knobs ----------------
    jobs = ["cashier", "waiter"]
    days = list(range(1, args.days + 1))
    intervals = list(range(args.start_interval, args.start_interval + args.intervals_per_day))

    # Shift templates (per job): (suffix, job, start_t, length, unpaid_breaks_Bj)
    # Coverage convention assumed by your model: t in range(start_t, start_t+length)  (exclusive end)
    # If you instead use inclusive end, increase length by +1.
    shift_templates = [
        ("morning", "cashier", args.start_interval + 0,  17, 0),  # 07:00–15:30 (t=14..30)
        ("evening", "cashier", args.start_interval + 10, 17, 0),  # 12:00–20:30 (t=24..40)
        ("morning", "waiter",  args.start_interval + 0,  17, 0),  # 07:00–15:30 (t=14..30)
        ("evening", "waiter",  args.start_interval + 10, 17, 0),  # 12:00–20:30 (t=24..40)
    ]

    # ---------------- employees.csv ----------------
    employees_rows, employees = [], []
    for idx in range(1, args.employees + 1):
        eid = f"e{idx}"
        employees.append(eid)
        typ = random.choice(["FT", "PT20", "PT25"])
        base = {"FT": 8.0, "PT20": 7.5, "PT25": 7.8}[typ]
        wage = round(base + random.uniform(-0.3, 0.3), 2)
        employees_rows.append([eid, f"Emp{idx}", typ, wage])
    write_csv_semicolon(out_dir / "employees.csv",
                        ["employee_id","name","type","hourly_cost"],
                        employees_rows)

    # ---------------- skills.csv ----------------
    # Everyone can cashier; ~60% can waiter
    skills_rows = []
    for eid in employees:
        skills_rows.append([eid, "cashier"])
        if random.random() < 0.6:
            skills_rows.append([eid, "waiter"])
    write_csv_semicolon(out_dir / "skills.csv",
                        ["employee_id","job"],
                        skills_rows)
    
    # ---------------- shifts.csv ----------------
    # One row per day per template. shift_id pattern: <job>_<suffix>_d<day>
    shifts_rows = []
    shift_ids_per_day = {d: [] for d in days}
    for d in days:
        for (suffix, job, s, L, Bj) in shift_templates:
            sid = f"{job}_{suffix}_d{d}"
            shift_ids_per_day[d].append((sid, job, s, L, Bj))
            shifts_rows.append([sid, d, job, s, L, Bj])
    write_csv_semicolon(out_dir / "shifts.csv",
                        ["shift_id","day","job","start_t","length","unpaid_breaks_Bj"],
                        shifts_rows)
    
    # ---------------- availability.csv ----------------
    # Probability patterns: mornings easier to cover; weekends slightly lower
    availability_rows = []
    for d in days:
        for (sid, job, s, L, Bj) in shift_ids_per_day[d]:
            is_morning = ("morning" in sid)
            # base probability by job/shift
            if job == "waiter":
                p = 0.55 if is_morning else 0.45
            else:  # cashier
                p = 0.70 if is_morning else 0.55
            # simple weekend effect (assuming day numbers 1..7, 7 treated as weekend)
            if (d % 7) in (6, 0):  # adjust if you later use real calendar
                p = max(0.0, p - 0.05)
            for eid in employees:
                if random.random() < p:
                    availability_rows.append([eid, d, sid, 1])
    write_csv_semicolon(out_dir / "availability.csv",
                        ["employee_id","day","shift_id","available"],
                        availability_rows)

    # ---------------- demand.csv ----------------
    # Create peaks across the longer day (28 intervals): a morning and an evening wave
    def demand_for(job, t):
        # Morning peak: start..start+7   Evening peak: start+16..start+23
        peak_m = 1 if (args.start_interval <= t <= args.start_interval + 7) else 0
        peak_e = 1 if (args.start_interval + 16 <= t <= args.start_interval + 23) else 0
        val = peak_m + peak_e
        # Slightly less waiter demand than cashier by default (tweak as you want)
        if job == "waiter":
            val = max(0, val - 1)
        return val

    demand_rows = []
    for d in days:
        for t in intervals:
            for job in jobs:
                mn = demand_for(job, t)
                pref = mn + (1 if (mn > 0 and random.random() < 0.3) else 0)
                demand_rows.append([d, t, job, pref, mn])
    write_csv_semicolon(out_dir / "demand.csv",
                        ["day","t","job","preferred","min"],
                        demand_rows)

    print(f"✔ Generated {args.days} days × {len(shift_templates)} shift-templates × {len(employees)} employees into {out_dir}")
    print(f"   Intervals per day: {args.intervals_per_day} (IDs {intervals[0]}..{intervals[-1]})")

if __name__ == "__main__":
    main()
