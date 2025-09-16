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

    # penalty weights (tune these)
    m.pen_pref = Param(initialize=1.0)   # weight for missing preferred staff
    m.pen_min  = Param(initialize=10.0)  # weight for missing minimum staff (should be >> pen_pref)

    # --- Decision Variables ---
    m.x = Var(m.I, m.J, m.D, within=Binary)

    # slack variables for unmet staffing (non-negative integers are fine)
    m.slack_pref = Var(m.K, m.D, m.T, domain=NonNegativeIntegers)
    m.slack_min  = Var(m.K, m.D, m.T, domain=NonNegativeIntegers)

    # --- Objective: Minimize wage cost + penalties ---
    def obj_rule(m):
        # paid intervals per assignment = (Tj - Bj)
        paid_intervals = sum((m.Lj[j] - m.Bj[j]) * m.x[i, j, d] for i in m.I for j in m.J for d in m.D)
        wage_cost = INTERVAL_HOURS * sum(m.cost[i] * (m.Lj[j] - m.Bj[j]) * m.x[i, j, d] for i in m.I for j in m.J for d in m.D)
        # penalty terms (sum of slacks)
        pref_pen = m.pen_pref * sum(m.slack_pref[k, d, t] for k in m.K for d in m.D for t in m.T)
        min_pen  = m.pen_min  * sum(m.slack_min[k, d, t]  for k in m.K for d in m.D for t in m.T)
        return wage_cost + pref_pen + min_pen
    m.obj = Objective(rule=obj_rule, sense=minimize)


    # --- Constraints ---

    # (1) Availability: you can only assign if available
    def avail_rule(m, i, j, d):
        return m.x[i,j,d] <= m.avail[i,j,d]
    m.avail_constr = Constraint(m.I, m.J, m.D, rule=avail_rule)

      # (2) Skill: you can only assign shift j if employee i has the skill for job k(j)
    def skill_rule(m, i, j, d):
        k = data['jobs_of'][j]
        return m.x[i,j,d] <= m.skill[i ,k]
    m.skill_constr = Constraint(m.I, m.J, m.D, rule=skill_rule)
    

    # (15) One shift per day per employee
    def one_shift_rule(m, i, d):
        return sum(m.x[i,j,d] for j in m.J) <= 1
    m.one_shift_constr = Constraint(m.I, m.D, rule=one_shift_rule)

    # helper: how many workers assigned to job k at (d, t)
    def assigned_kdt(m, k, d, t):
        # count all employees assigned to any shift j that:
        #   (a) belongs to job k, and (b) covers interval t on day d
        return sum(m.covers[j, t] * m.x[i, j, d] for i in m.I for j in m.J if m.job_of[j] == k)

    # (30) Preferred staffing: assigned + slack_pref >= preferred demand
    def preferred_staffing(m, k, d, t):
        return assigned_kdt(m, k, d, t) + m.slack_pref[k, d, t] >= m.prefReq[k, d, t]
    m.prefered_staff_constraint = Constraint(m.K, m.D, m.T, rule=preferred_staffing)

    # (31) Minimum staffing: assigned + slack_min >= minimum demand
    def minimum_staffing(m, k, d, t):
        return assigned_kdt(m, k, d, t) + m.slack_min[k, d, t] >= m.minReq[k, d, t]
    m.minimum_staff_constraint = Constraint(m.K, m.D, m.T, rule=minimum_staffing)

    return m