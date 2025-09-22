import csv
from collections import defaultdict

def load_data(path):
    data = {}

    # Load employees
    employees = []
    wage = {}
    emp_type = {}
    with open(f"{path}/employees.csv", newline="", encoding="utf-8-sig") as f:       
        r = csv.DictReader(f, delimiter=';')
        for row in r:
            i = row ["employee_id"]
            employees.append(i)
            wage[i] = float(row["hourly_cost"])
            emp_type[i] = row["type"]
    data['employees'] = employees
    data['wage'] = wage
    data['emp_type'] = emp_type

    #jobs (from skills.scv)
    skills_sparse = {}
    jobs = set()
    with open(f"{path}/skills.csv", newline="", encoding="utf-8-sig") as f:
        r = csv.DictReader(f, delimiter=';')
        for row in r:
            skills_sparse[(row["employee_id"], row["job"])] = 1
            jobs.add(row["job"])
    data['skills'] = skills_sparse
    data['jobs'] = sorted(jobs)

    # Load shifts - there is room for improvement here (considering days coverage instead of pre-alocating a shift to a day; considering any impact when there's unpaid breaks)
    shifts = []
    jobs_of = {}
    start_j = {}
    Lj = {}
    unpaid = {}
    covers = defaultdict(lambda: defaultdict(int)) #covers [j][t] =1
    days = set()
    intervals = set()
    intervals_from_covers = set()


    with open(f"{path}/shifts.csv", newline="", encoding="utf-8-sig") as f:
        r = csv.DictReader(f, delimiter=';')
        for row in r:
            j = row["shift_id"];d = int(row["day"])
            k = row["job"];s = int(row["start_t"]);L = int(row["length"])
            b = int(row["unpaid_breaks_Bj"])
            shifts.append(j); days.add(d)
            jobs_of[j] = k; start_j[j] = s; Lj[j] = L; unpaid[j] = b
            for t in range(s, s+L):
                covers[j][t] = 1
                intervals_from_covers.add(t)
    data['shifts'] = shifts
    data['jobs_of'] = jobs_of
    data['days'] = sorted(days)
    data['start_j'] = start_j
    data['Lj'] = Lj
    data['unpaid'] = unpaid
    data["covers"] = {(j, t): 1 for j in shifts for t in covers[j].keys()} #if we include breaks we need to consider them in the covers

    '''
    avail = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    with open(f"{path}/availability.csv", newline="", encoding="utf-8-sig") as f:
        r = csv.DictReader(f, delimiter=';')
        for row in r:
            avail[row["employee_id"]][row["shift_id"]][int(row["day"])] = int (row["available"])
    data['availability'] = { (i,j,d): avail[i][j][d] for i in employees for j in shifts for d in data["days"] }
    '''

    # Load demand
    intervals_from_demand = set()
    demand_pref = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    demand_min =  defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    with open(f"{path}/demand.csv", newline="", encoding="utf-8-sig") as f:
        r = csv.DictReader(f, delimiter=';')
        for row in r:
            d = int(row["day"]); t= int(row["t"]); k = row["job"]
            demand_pref [k][d][t] = int(row["preferred"])
            demand_min [k][d][t] = int(row["min"])
            intervals_from_demand.add(t)
    data["intervals"] = sorted(intervals_from_covers | intervals_from_demand)
    data["pref_kdt"] = { (k,d,t): demand_pref[k][d][t] for k in data["jobs"] for d in data["days"] for t in data["intervals"] }
    data["min_kdt"] = { (k,d,t): demand_min[k][d][t] for k in data["jobs"] for d in data["days"] for t in data["intervals"] }

    # ---- Load availability from unavailability (PLACE IT HERE) ----
    blocked = load_unavailability(path, data["employees"], data["days"])
    data["blocked"] = blocked   # optional, if you want to keep it

    # Derive shift availability for FT (still needed for X set)
    data["availability"] = derive_shift_availability_from_grid (data["shifts"], data["covers"], data["employees"], data["days"], blocked)

    # employee subsets (FT / PT20 / PT25) used by constraints (16–20) in your PDF
    data["FT"] = [i for i,t in emp_type.items() if t=="FT"]
    data["PT20"] = [i for i,t in emp_type.items() if t=="PT20"]
    data["PT25"] = [i for i,t in emp_type.items() if t=="PT25"]
    data["PT"] = data["PT20"] + data["PT25"]

    # ----- compute a safe penalty for minimum understaffing ----- it is not being used, but if we want to it is just needed to delete the fixed value of pen_min
    INTERVAL_HOURS = 0.5
    max_wage = max(data["wage"].values())
    max_paid_intervals = max(data["Lj"][j] - data["unpaid"][j] for j in data["shifts"])
    # Upper bound on the total cost of assigning any single shift
    upper_shift_cost = max_wage * INTERVAL_HOURS * max_paid_intervals
    # Make paying 1 unit of min-slack more expensive than adding any single shift
    data["pen_min"] = 10e6 #upper_shift_cost * 2.0
    # Keep preferred penalty small (nice-to-have)
    data["pen_pref"] = 10.0


    # ----- Build sparse candidate set X = {(i,j,d) that are feasible} -----
    # Conditions we’ll enforce now (filter out impossible triplets):
    #  - employee has skill for job_of_j[j]
    #  - employee is available for (j,d)

    X = []
    for i in data["employees"]:
        for j in data["shifts"]:
            k = data["jobs_of"][j] #job required for shift j
            has_skill = data["skills"].get((i, k), 0)
            if not has_skill:
                continue       
            for d in data["days"]:
                a = data["availability"].get((i, j, d), 0)
                if a == 1 :
                    X.append((i, j, d))

    # Store it
    data["X"] = X


    return data

def load_unavailability(path, employees, days):
    blocked = set()  # {(i,d,t)}
    with open(f"{path}/unavailability.csv", newline="", encoding="utf-8-sig") as f:
        r = csv.DictReader(f, delimiter=';')
        for row in r:
            i = row["employee_id"]
            if i not in employees: continue
            d = int(row["day"])
            if d not in days: continue
            s = int(row["start_t"]); e = int(row["end_t"])
            for t in range(s, e):
                blocked.add((i, d, t))
    return blocked


def derive_shift_availability_from_grid(shifts, covers, employees, days, blocked):
    """
    Build a sparse dict {(i,j,d):1} iff employee i is available on all covered t of shift j on day d.
    covers is sparse {(j,t):1}.
    This applies just for FT.
    """
    by_shift_t = defaultdict(list)
    for (j, t), _ in covers.items():
        by_shift_t[j].append(t)

    avail_shift = {}
    for i in employees:
        for j in shifts:
            ts = by_shift_t.get(j, [])
            if not ts:   # shift with no coverage slots? then trivially available
                for d in days:
                    avail_shift[(i, j, d)] = 1
                continue
            for d in days:
                ok = True
                for t in ts:
                    if (i, d, t) in blocked:  # if blocked, then not available
                        ok = False
                        break
                if ok:
                    avail_shift[(i, j, d)] = 1
    return avail_shift