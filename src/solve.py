from pyomo.environ import SolverFactory
from io_utilis import load_data
from model import build_model

data = load_data("data/")
m = build_model(data)

solver = SolverFactory("cbc")
solver.options["ratioGap"] = 0.02   # stop when within 2% of optimal
solver.options["seconds"] = 60      # time limit
solver.options["threads"] = 0       # use all cores
result = solver.solve(m, tee=True)

