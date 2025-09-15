from pyomo.environ import SolverFactory
from io_utils import load_data
from model import build_model

data = load_data("data/")
m = build_model(data)

solver = SolverFactory('cbc')
solver.solve(m, tee=True)

