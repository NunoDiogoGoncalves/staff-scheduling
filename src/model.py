from pyomo.environ import *

INTERVAL_HOURS = 0.5  # Each time interval is 30 minutes

def build_model(data,flex):
    m = ConcreteModel()

    # --- Sets ---
    m.I = Set(initialize=data['employees'])  #employees
    m.J = Set(initialize=data['shifts']) #shifts
    m.D = Set(initialize=data['days']) #days
    m.T = Set(initialize=data['intervals']) #time intervals
    m.K = Set(initialize=data['jobs']) #jobs
    m.X = Set(dimen=3, initialize=data["X"])  # sparse candidate set for variables. Each element is a tuple (i,j,d)
    m.Y = Set(initialize=flex["Y"])  #Flexible shifts (patterns)

    # --- Parameters (fixed) ---
    m.cost = Param(m.I, initialize=data['wage'], within=NonNegativeReals) # wage cost per hour per employee
    m.Lj = Param(m.J, initialize=data['Lj'], within=NonNegativeIntegers)  # Length of shift j in number of intervals
    m.Bj = Param(m.J, initialize=data['unpaid'], within=NonNegativeIntegers) # Unpaid breaks in number of intervals for shift j
    m.covers = Param(m.J, m.T, initialize=data['covers'], default=0, within=Binary)  # 1 if shift j covers time interval t, 0 otherwise
    m.job_of = Param(m.J, initialize=data["jobs_of"], within=m.K)
    m.avail = Param(m.I,m.J,m.D, initialize=data['availability'], default=0, within=Binary)  # Availability of employee i for shift j on day 
    m.skill = Param(m.I, m.K, initialize=data['skills'], default=0, within=Binary)
    m.prefReq = Param(m.K, m.D, m.T, initialize=data["pref_kdt"], default=0)
    m.minReq  = Param(m.K, m.D, m.T, initialize=data["min_kdt"], default=0)
    m.pen_pref = Param(initialize=data["pen_pref"])
    m.pen_min  = Param(initialize=data["pen_min"])
    # ----- compute a safe penalty for minimum understaffing -----
    #INTERVAL_HOURS = 0.5
    #max_wage = max(data["wage"].values())
    #max_paid_intervals = max(data["Tj"][j] - data["Bj"][j] for j in data["shifts"])
    # Upper bound on the total cost of assigning any single shift
    #upper_shift_cost = max_wage * INTERVAL_HOURS * max_paid_intervals
    # Make paying 1 unit of min-slack more expensive than adding any single shift
    #data["pen_min"] = upper_shift_cost * 2.0

    # --- Parameters (flex) ---
    m.P_i = Param(m.Y, initialize=flex["P_i"], within=Any)
    m.P_k = Param(m.Y, initialize=flex["P_k"], within=Any)
    m.P_d = Param(m.Y, initialize=flex["P_d"], within=Any)
    m.P_s = Param(m.Y, initialize=flex["P_s"], within=NonNegativeIntegers)
    m.P_L = Param(m.Y, initialize=flex["P_L"], within=NonNegativeIntegers)
    m.covP  = Param(m.Y, m.T, initialize=flex["covP"], default=0, within=Binary)
    m.paidP = Param(m.Y, initialize=flex["paidP"], within=NonNegativeIntegers)
    m.costP = Param(m.Y, initialize=flex["costP"], within=NonNegativeReals)


    # --- Decision variables ---
    m.x = Var(m.X, domain=Binary)
    m.y = Var(m.Y, domain=Binary)     # flexible
    m.slack_pref = Var(m.K, m.D, m.T, domain=NonNegativeReals)     # slack variables for unmet staffing (non-negative integers are fine)
    m.slack_min  = Var(m.K, m.D, m.T, domain=NonNegativeReals)     # slack variables for unmet staffing (non-negative integers are fine)


    # --- Objective: Minimize wage cost + penalties ---
    def obj_rule(m):
        wage_fixed = INTERVAL_HOURS * sum(m.cost[i] * (m.Lj[j] - m.Bj[j]) * m.x[i, j, d] for (i, j, d) in m.X)
        wage_flex  = sum(m.costP[p] * m.y[p] for p in m.Y)
        pref_pen   = m.pen_pref * sum(m.slack_pref[k, d, t] for k in m.K for d in m.D for t in m.T)
        min_pen    = m.pen_min  * sum(m.slack_min[k, d, t]  for k in m.K for d in m.D for t in m.T)
        return wage_fixed + wage_flex + pref_pen + min_pen
    m.obj = Objective(rule=obj_rule, sense=minimize)


    # --- Constraints ---

    # (1) Availability: you can only assign if available -> Can be omitted if we build X correctly
    #def avail_rule(m, i, j, d):
        #if (i, j, d) not in m.X:   # variable doesn’t exist → skip
            #return Constraint.Skip
        #return m.x[i, j, d] <= m.avail[i, j, d]
    #m.Availability = Constraint(m.X, rule=avail_rule)

    def skill_rule(m, i, j, d):
        if (i, j, d) not in m.X:
            return Constraint.Skip
        k = m.job_of[j]
        return m.x[i, j, d] <= m.skill[i, k]
    m.SkillOK = Constraint(m.X,rule=skill_rule)
    

    # (15) One shift per day per employee
    # One shift per (i,d) across fixed + flexible
    id_pairs = sorted({(i, d) for (i, _, d) in data["X"]} |
                      {(flex["P_i"][p], flex["P_d"][p]) for p in flex["Y"]})
    m.ID = Set(dimen=2, initialize=id_pairs)

    # index patterns by (i,d) for speed
    patterns_by_id = {}
    for p in flex["Y"]:
        patterns_by_id.setdefault((flex["P_i"][p], flex["P_d"][p]), []).append(p)

    def one_per_day(m, i, d):
        fixed_sum = sum(m.x[ii, j, dd] for (ii, j, dd) in m.X if ii == i and dd == d)
        plist = patterns_by_id.get((i, d), [])
        flex_sum = sum(m.y[p] for p in plist)
        return fixed_sum + flex_sum <= 1
    m.OneShiftPerDay = Constraint(m.ID, rule=one_per_day)

    # Coverage (fixed + flex)
    def assigned_kdt(m, k, d, t):
        fixed = sum(m.covers[j, t] * m.x[i, j, dd] for (i, j, dd) in m.X if dd == d and m.job_of[j] == k)
        flex  = sum(m.covP[p, t]  * m.y[p]          for p in m.Y if m.P_k[p] == k and m.P_d[p] == d)
        return fixed + flex
    # (30) Preferred staffing: assigned + slack_pref >= preferred demand
    def preferred_staffing(m, k, d, t):
        return assigned_kdt(m, k, d, t) + m.slack_pref[k, d, t] >= m.prefReq[k, d, t]
    m.Preferred = Constraint(m.K, m.D, m.T, rule=preferred_staffing)
    # (31) Minimum staffing: assigned + slack_min >= minimum demand
    def minimum_staffing(m, k, d, t):
        return assigned_kdt(m, k, d, t) + m.slack_min[k, d, t] >= m.minReq[k, d, t]
    m.Minimum = Constraint(m.K, m.D, m.T, rule=minimum_staffing)

    return m