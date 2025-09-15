from pyomo.environ import *


def build_model(data):
    m = ConcreteModel()

    # Sets
    m.I = Set(initialize=data['employees'])  
    m.J = Set(initialize=data['shifts'])
    m.D = Set(initialize=data['days'])
    m.K = Set(initialize=data['jobs'])

    # Parameters
    m.avail = Param(m.I,m.J,m.D, initialize=data['availability'], within=Binary)  # Availability of employee i for shift j on day 
    m.skill = Param(m.I, m.K, initialize=data['skills'], within=Binary)
    m.cost = Param(m.I, initialize=data['wage'])
    m.demand = Param(m.K, m.D, initialize=data['demand'])


    # Decision Variables
    m.x = Var(m.I, m.J, m.D, within=Binary)

    # Objective: Minimize wage cost (basic version)
    def obj_rule(m):
        return sum(m.cost[i] * m.x[i,j,d] for i in m.I for j in m.J for d in m.D)
    m.obj = Objective(rule=obj_rule, sense=minimize)

    # Constraint: availability
    def avail_rule(m, i, j, d):
        return m.x[i,j,d] <= m.avail[i,j,d]
    m.avail_constr = Constraint(m.I, m.J, m.D, rule=avail_rule)

    # Constraint: one shift per day
    def one_shift_rule(m, i, d):
        return sum(m.x[i,j,d] for j in m.J) <= 1
    m.one_shift_constr = Constraint(m.I, m.D, rule=one_shift_rule)

    return m