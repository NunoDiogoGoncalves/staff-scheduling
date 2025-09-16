from pyomo.environ import *

INTERVAL_HOURS = 0.5  # Each time interval is 30 minutes

def build_model(data):
    m = ConcreteModel()

    # --- Sets ---
    m.I = Set(initialize=data['employees'])  #employees
    m.J = Set(initialize=data['shifts']) #shifts
    m.D = Set(initialize=data['days']) #days
    m.T = Set(initialize=data['intervals']) #time intervals
    m.K = Set(initialize=data['jobs']) #jobs

    # sparse candidate set for variables
    m.X = Set(dimen=3, initialize=data["X"])  # each element is a tuple (i,j,d)

    # --- Parameters ---
    # wage cost per hour per employee
    m.cost = Param(m.I, initialize=data['wage'], within=NonNegativeReals)

    # shift properties
    m.Lj = Param(m.J, initialize=data['Lj'], within=NonNegativeIntegers)  # Length of shift j in number of intervals
    m.Bj = Param(m.J, initialize=data['unpaid'], within=NonNegativeIntegers) # Unpaid breaks in number of intervals for shift j
    m.covers = Param(m.J, m.T, initialize=data['covers'], default=0, within=Binary)  # 1 if shift j covers time interval t, 0 otherwise
    m.job_of = Param(m.J, initialize=data["jobs_of"], within=m.K)

    # availability and skills
    m.avail = Param(m.I,m.J,m.D, initialize=data['availability'], default=0, within=Binary)  # Availability of employee i for shift j on day 
    m.skill = Param(m.I, m.K, initialize=data['skills'], default=0, within=Binary)

    #staff target per job per day
    m.prefReq = Param(m.K, m.D, m.T, initialize=data["pref_kdt"], default=0)
    m.minReq  = Param(m.K, m.D, m.T, initialize=data["min_kdt"], default=0)

    # ----- compute a safe penalty for minimum understaffing -----
    #INTERVAL_HOURS = 0.5
    #max_wage = max(data["wage"].values())
    #max_paid_intervals = max(data["Tj"][j] - data["Bj"][j] for j in data["shifts"])
    # Upper bound on the total cost of assigning any single shift
    #upper_shift_cost = max_wage * INTERVAL_HOURS * max_paid_intervals
    # Make paying 1 unit of min-slack more expensive than adding any single shift
    #data["pen_min"] = upper_shift_cost * 2.0

    # penalty weights (tune these)
    m.pen_pref = Param(initialize=data["pen_pref"])
    m.pen_min  = Param(initialize=data["pen_min"])

    # Decision variable only on feasible triplets
    m.x = Var(m.X, domain=Binary)

    # slack variables for unmet staffing (non-negative integers are fine)
    m.slack_pref = Var(m.K, m.D, m.T, domain=NonNegativeIntegers)
    m.slack_min  = Var(m.K, m.D, m.T, domain=NonNegativeIntegers)

    # --- Objective: Minimize wage cost + penalties ---
    def obj_rule(m):
        # paid intervals per assignment = (Tj - Bj)
        paid_intervals = sum((m.Lj[j] - m.Bj[j]) * m.x[i, j, d] for (i, j, d) in m.X)
        wage_cost = INTERVAL_HOURS * sum(m.cost[i] * (m.Lj[j] - m.Bj[j]) * m.x[i, j, d] for (i, j, d) in m.X)
        # penalty terms (sum of slacks)
        pref_pen = m.pen_pref * sum(m.slack_pref[k, d, t] for k in m.K for d in m.D for t in m.T)
        min_pen  = m.pen_min  * sum(m.slack_min[k, d, t]  for k in m.K for d in m.D for t in m.T)
        return wage_cost + pref_pen + min_pen
    m.obj = Objective(rule=obj_rule, sense=minimize)


    # --- Constraints ---

    # (1) Availability: you can only assign if available
    def avail_rule(m, i, j, d):
        if (i, j, d) not in m.X:   # variable doesn’t exist → skip
            return Constraint.Skip
        return m.x[i, j, d] <= m.avail[i, j, d]
    m.Availability = Constraint(m.X, rule=avail_rule)

    def skill_rule(m, i, j, d):
        if (i, j, d) not in m.X:
            return Constraint.Skip
        k = m.job_of[j]
        return m.x[i, j, d] <= m.skill[i, k]
    m.SkillOK = Constraint(m.X,rule=skill_rule)
    

    # (15) One shift per day per employee
    def one_per_day(m, i, d):
        vars_today = [m.x[ii, j, dd] for (ii, j, dd) in m.X if ii == i and dd == d]
        if vars_today:
            return sum(vars_today) <= 1
        else:
            return Constraint.Skip   # no feasible shifts → skip constraint
    m.OneShiftPerDay = Constraint(m.I, m.D, rule=one_per_day)

    # helper: how many workers assigned to job k at (d, t)
    def assigned_kdt(m, k, d, t):
    # count employees assigned on (d) to any shift j of job k that covers t
        return sum(m.covers[j, t] * m.x[i, j, dd] for (i, j, dd) in m.X if dd == d and m.job_of[j] == k)

    # (30) Preferred staffing: assigned + slack_pref >= preferred demand
    def preferred_staffing(m, k, d, t):
        return assigned_kdt(m, k, d, t) + m.slack_pref[k, d, t] >= m.prefReq[k, d, t]
    m.Preferred = Constraint(m.K, m.D, m.T, rule=preferred_staffing)


    # (31) Minimum staffing: assigned + slack_min >= minimum demand
    def minimum_staffing(m, k, d, t):
        return assigned_kdt(m, k, d, t) + m.slack_min[k, d, t] >= m.minReq[k, d, t]
    m.Minimum = Constraint(m.K, m.D, m.T, rule=minimum_staffing)

    return m