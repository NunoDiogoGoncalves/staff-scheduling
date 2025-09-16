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
            i = row ["employees_id"]
            employees.append(i)
            wage[i] = float(row["hourly_cost"])
            emp_type[i] = row["type"]
    data['employees'] = employees
    data['wage'] = wage
    data['emp_type'] = emp_type

    #jobs (from skills.scv)
    skills = defaultdict(lambda: defaultdict(int))
    jobs = set()
    with open(f"{path}/skills.csv", newline="", encoding="utf-8-sig") as f:
        r = csv.DictReader(f, delimiter=';')
        for row in r:
            skills[row["employee_id"]][row["job"]] = 1
            jobs.add(row["job"])
    data['skills'] = {(i, k): skills[i][k] for i in employees for k in jobs}  
    data['jobs'] = sorted(jobs)

    # Load shifts - there is room for improvement here (considering days in coverage too; difference between Tj and length of shift Lj)
    shifts = []
    job_of = {}
    start_j = {}
    Lj = {}
    unpaid = {}
    covers = defaultdict(lambda: defaultdict(int)) #covers [j][t] =1
    days = set()
    intervals = set()

    with open(f"{path}/shifts.csv", newline="", encoding="utf-8-sig") as f:
        r = csv.DictReader(f, delimiter=';')
        for row in r:
            j = row["shift_id"];d = int(row["day"])
            k = row["job"];s = int(row["start_t"]);L = int(row["length"])
            b = int(row["unpaid_breaks_Bj"])
            shifts.append(j); days.add(d)
            job_of[j] = k; start_j[j] = s; Lj[j] = L; unpaid[j] = b
            for t in range(s, s+L+1):
                covers[j][t] = 1
                intervals.add(t)
    data['shifts'] = shifts
    data['jobs_of'] = job_of
    data['intervals'] = sorted(intervals)
    data['days'] = sorted(days)
    data['start_j'] = start_j
    data['Lj'] = Lj
    data['unpaid'] = unpaid
    data['covers'] = { (j,t): covers[j][t] for j in shifts for t in intervals }

    # Load availability
    avail = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    with open(f"{path}/availability.csv", newline="", encoding="utf-8-sig") as f:
        r = csv.DictReader(f, delimiter=';')
        for row in r:
            avail[row["employee_id"]][row["shift_id"]][int(row["day"])] = int (row["available"])
    data['availability'] = { (i,j,d): avail[i][j][d] for i in employees for j in shifts for d in data["days"] }


    # Load demand
    pref = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    min =  defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    with open(f"{path}/demand.csv", newline="", encoding="utf-8-sig") as f:
        r = csv.DictReader(f, delimiter=';')
        for row in r:
            d = int(row["day"]); t= int(row["t"]); k = row["job"]
            pref [k][d][t] = int(row["preferred"])
            min [k][d][t] = int(row["min"])
            intervals.add(t)
    data["pref_kdt"] = { (k,d,t): pref[k][d][t] for k in data["jobs"] for d in data["days"] for t in data["intervals"] }
    data["min_kdt"] = { (k,d,t): min[k][d][t] for k in data["jobs"] for d in data["days"] for t in data["intervals"] }

    # employee subsets (FT / PT20 / PT25) used by constraints (16–20) in your PDF
    data["FT"] = [i for i,t in emp_type.items() if t=="FT"]
    data["PT20"] = [i for i,t in emp_type.items() if t=="PT20"]
    data["PT25"] = [i for i,t in emp_type.items() if t=="PT25"]
    data["PT"] = data["PT20"] + data["PT25"]

    # ----- compute a safe penalty for minimum understaffing -----
    INTERVAL_HOURS = 0.5
    max_wage = max(data["wage"].values())
    max_paid_intervals = max(data["Lj"][j] - data["unpaid"][j] for j in data["shifts"])
    # Upper bound on the total cost of assigning any single shift
    upper_shift_cost = max_wage * INTERVAL_HOURS * max_paid_intervals
    # Make paying 1 unit of min-slack more expensive than adding any single shift
    data["pen_min"] = 10e6 #upper_shift_cost * 2.0
    # Keep preferred penalty small (nice-to-have)
    data["pen_pref"] = 1.0
        
    return data