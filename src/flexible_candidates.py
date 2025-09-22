def build_flexible_candidates (data, allowed_lengths = (8,9,10,11,12,13,14), start_window=None):

    INTERVAL_HOURS = 0.5  # each interval is 30 minutes
    PT = set(data["PT"])
    employees = data["employees"]
    jobs = data["jobs"]
    days = data["days"]
    availability = data["availability"]      # (i,j,d) for fixed shifts; not used here
    skills = data["skills"]                  # sparse {(i,k):1}
    wage = data["wage"]
    intervals = data["intervals"]
    blocked = data["blocked"]                # set {(i,d,t)}


    # If start_window given, restrict start times
    if start_window is None:
        start_times = intervals
    else:
        lo, hi = start_window
        start_times = [t for t in intervals if lo <= t <= hi]

    # For flexible shifts we don’t rely on fixed shift ids; we check availability directly on time-grid.
    # Reuse your 'covers' idea but per pattern p.
    Y = []          # a flat list of pattern IDs, e.g. ["P0", "P1", "P2", ...]
    P_i = {}        # maps pattern -> employee (i)
    P_k = {}        # maps pattern -> job (k)
    P_d = {}        # maps pattern -> day (d)
    P_s = {}        # maps pattern -> start time index (s)
    P_L = {}        # maps pattern -> length in intervals (L)
    covP = {}       # maps (pattern, t) -> 1 if pattern covers time interval t
    paidP = {}      # maps pattern -> number of paid intervals (L minus breaks, if any)
    costP = {}      # maps pattern -> total wage cost if assigned

    pid = 0
    for i in employees:
        if i not in PT:
            continue
        for k in jobs:
            if skills.get((i, k), 0) != 1:
                continue
            for d in days:
                for s in start_times:
                    for L in allowed_lengths:
                        end_t = s + L
                        # ensure we remain on valid indices
                        if any((t not in intervals) for t in range(s, end_t)):
                            continue
                        # feasibility: no blocked slots in [s, end_t)
                        # (missing from blocked = available)
                        feas = True
                        for t in range(s, end_t):
                            if (i, d, t) in blocked:
                                feas = False
                                break
                        if not feas:
                            continue

                        p = f"P{pid}"; pid += 1
                        Y.append(p)
                        P_i[p] = i
                        P_k[p] = k
                        P_d[p] = d
                        P_s[p] = s
                        P_L[p] = L
                        for t in range(s, end_t):
                            covP[(p, t)] = 1
                        paidP[p] = L
                        costP[p] = wage[i] * INTERVAL_HOURS * paidP[p]

    return {
        "Y": Y, "P_i": P_i, "P_k": P_k, "P_d": P_d, "P_s": P_s, "P_L": P_L,
        "covP": covP, "paidP": paidP, "costP": costP
    }