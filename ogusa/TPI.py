# imports
import numpy as np
import pickle
import scipy.optimize as opt
from dask import delayed, compute
import dask.multiprocessing
from ogusa import tax, utils, household, firm, fiscal
from ogusa import aggregates as aggr
from ogusa.constants import SHOW_RUNTIME
import os
import warnings


if not SHOW_RUNTIME:
    warnings.simplefilter("ignore", RuntimeWarning)

'''
Set minimizer tolerance
'''
MINIMIZER_TOL = 1e-13

'''
Set flag for enforcement of solution check
'''
ENFORCE_SOLUTION_CHECKS = True


def get_initial_SS_values(p):
    '''
    Get values of variables for the initial period and the steady state
    equilibrium values.

    Args:
        p (OG-USA Specifications object): model parameters

    Returns:
        (tuple): initial period and steady state values:

            * initial_values (tuple): initial period variable values,
                (b_sinit, b_splus1init, factor, initial_b, initial_n)
            * ss_vars (dictionary): dictionary with steady state
                solution results
            * theta (Numpy array): steady-state retirement replacement
                rates, length J
            * baseline_values (tuple): (TRbaseline, Gbaseline,
                D0_baseline), lump sum transfer and government spending
                amounts from the baseline model run

    '''
    baseline_ss = os.path.join(p.baseline_dir, "SS", "SS_vars.pkl")
    ss_baseline_vars = utils.safe_read_pickle(baseline_ss)
    factor = ss_baseline_vars['factor_ss']
    B0 = aggr.get_B(ss_baseline_vars['bssmat_splus1'], p, 'SS', True)
    initial_b = (ss_baseline_vars['bssmat_splus1'] *
                 (ss_baseline_vars['Bss'] / B0))
    initial_n = ss_baseline_vars['nssmat']
    TRbaseline = None
    Gbaseline = None
    if p.baseline_spending:
        baseline_tpi = os.path.join(
            p.baseline_dir, "TPI", "TPI_vars.pkl")
        tpi_baseline_vars = utils.safe_read_pickle(baseline_tpi)
        TRbaseline = tpi_baseline_vars['TR']
        Gbaseline = tpi_baseline_vars['G']

    if p.baseline:
        ss_vars = ss_baseline_vars
    else:
        reform_ss_path = os.path.join(p.output_base, "SS", "SS_vars.pkl")
        ss_vars = utils.safe_read_pickle(reform_ss_path)
    theta = ss_vars['theta']

    '''
    ------------------------------------------------------------------------
    Set other parameters and initial values
    ------------------------------------------------------------------------
    '''
    # Get an initial distribution of wealth with the initial population
    # distribution. When small_open=True, the value of K0 is used as a
    # placeholder for first-period wealth
    B0 = aggr.get_B(initial_b, p, 'SS', True)

    b_sinit = np.array(list(np.zeros(p.J).reshape(1, p.J)) +
                       list(initial_b[:-1]))
    b_splus1init = initial_b

    # Intial gov't debt must match that in the baseline
    if not p.baseline:
        baseline_tpi = os.path.join(
            p.baseline_dir, "TPI", "TPI_vars.pkl")
        tpi_baseline_vars = utils.safe_read_pickle(baseline_tpi)
        D0_baseline = tpi_baseline_vars['D'][0]
    else:
        D0_baseline = None

    initial_values = (B0, b_sinit, b_splus1init, factor, initial_b,
                      initial_n)
    baseline_values = (TRbaseline, Gbaseline, D0_baseline)

    return initial_values, ss_vars, theta, baseline_values


def firstdoughnutring(guesses, r, w, bq, tr, theta, factor, j,
                      initial_b, p):
    '''
    Solves the first entries of the upper triangle of the twist
    doughnut.  This is separate from the main TPI function because the
    values of b and n are scalars, so it is easier to just have a
    separate function for these cases.

    Args:
        guesses (Numpy array): initial guesses for b and n, length 2
        r (scalar): real interest rate
        w (scalar): real wage rate
        bq (scalar): bequest amounts by age
        tr (scalar): government transfer amount
        theta (Numpy array): retirement replacement rates, length J
        factor (scalar): scaling factor converting model units to dollars
        j (int): index of ability type
        initial_b (Numpy array): savings of agents alive at T=0,
            size = SxJ
        p (OG-USA Specifications object): model parameters

    Returns:
        euler errors (Numpy array): errors from first order conditions,
            length 2

    '''
    b_splus1 = float(guesses[0])
    n = float(guesses[1])
    b_s = float(initial_b[-2, j])

    # Find errors from FOC for savings and FOC for labor supply
    error1 = household.FOC_savings(np.array([r]), np.array([w]), b_s,
                                   np.array([b_splus1]), np.array([n]),
                                   np.array([bq]), factor,
                                   np.array([tr]), theta[j],
                                   p.e[-1, j], p.rho[-1],
                                   np.array([p.tau_c[0, -1, j]]),
                                   p.etr_params[0, -1, :],
                                   p.mtry_params[0, -1, :], None, j, p,
                                   'TPI_scalar')

    error2 = household.FOC_labor(
        np.array([r]), np.array([w]), b_s, b_splus1, np.array([n]),
        np.array([bq]), factor, np.array([tr]), theta[j], p.chi_n[-1],
        p.e[-1, j], np.array([p.tau_c[0, -1, j]]), p.etr_params[0, -1, :],
        p.mtrx_params[0, -1, :], None, j, p, 'TPI_scalar')

    if n <= 0 or n >= 1:
        error2 += 1e12
    if b_splus1 <= 0:
        error1 += 1e12
    return [np.squeeze(error1)] + [np.squeeze(error2)]


def twist_doughnut(guesses, r, w, bq, tr, theta, factor, j, s, t,
                   tau_c, etr_params, mtrx_params, mtry_params,
                   initial_b, p):
    '''
    Solves the upper triangle of time path iterations.  These are the
    agents who are alive at time T=0 so that we do not solve for their
    full lifetime (so of their life was before the model begins).

    Args:
        guesses (Numpy array): initial guesses for b and n, length 2s
        r (scalar): real interest rate
        w (scalar): real wage rate
        bq (Numpy array): bequest amounts by age, length s
        tr (scalar): government transfer amount
        theta (Numpy array): retirement replacement rates, length J
        factor (scalar): scaling factor converting model units to dollars
        j (int): index of ability type
        s (int): years of life remaining
        t (int): model period
        tau_c (Numpy array): consumption tax rates, size = sxJ
        etr_params (Numpy array): ETR function parameters,
            size = sxsxnum_params
        mtrx_params (Numpy array): labor income MTR function parameters,
            size = sxsxnum_params
        mtry_params (Numpy array): capital income MTR function
            parameters, size = sxsxnum_params
        initial_b (Numpy array): savings of agents alive at T=0,
            size = SxJ
        p (OG-USA Specifications object): model parameters

    Returns:
        euler errors (Numpy array): errors from first order conditions,
            length 2s

    '''
    length = int(len(guesses) / 2)
    b_guess = np.array(guesses[:length])
    n_guess = np.array(guesses[length:])

    if length == p.S:
        b_s = np.array([0] + list(b_guess[:-1]))
    else:
        b_s = np.array([(initial_b[-(s + 3), j])] + list(b_guess[:-1]))

    b_splus1 = b_guess
    w_s = w[t:t + length]
    r_s = r[t:t + length]
    n_s = n_guess
    chi_n_s = p.chi_n[-length:]
    e_s = p.e[-length:, j]
    rho_s = p.rho[-length:]

    error1 = household.FOC_savings(r_s, w_s, b_s, b_splus1, n_s, bq,
                                   factor, tr, theta, e_s, rho_s,
                                   tau_c, etr_params, mtry_params, t,
                                   j, p, 'TPI')

    error2 = household.FOC_labor(r_s, w_s, b_s, b_splus1, n_s, bq,
                                 factor, tr, theta, chi_n_s, e_s,
                                 tau_c, etr_params, mtrx_params, t, j,
                                 p, 'TPI')

    # Check and punish constraint violations
    mask1 = n_guess < 0
    error2[mask1] += 1e12
    mask2 = n_guess > p.ltilde
    error2[mask2] += 1e12
    mask4 = b_guess <= 0
    error2[mask4] += 1e12
    mask5 = b_splus1 < 0
    error2[mask5] += 1e12

    return list(error1.flatten()) + list(error2.flatten())


def inner_loop(guesses, outer_loop_vars, initial_values, j, ind, p):
    '''
    Given path of economic aggregates and factor prices, solves
    household problem.  This has been termed the inner-loop (in
    constrast to the outer fixed point loop that soves for GE factor
    prices and economic aggregates).

    Args:
        guesses (tuple): initial guesses for b and n, (guesses_b,
            guesses_n)
        outer_loop_vars (tuple): values for factor prices and economic
            aggregates used in household problem (r, w, r_hh, BQ, TR,
            theta)
        r (Numpy array): real interest rate on private capital
        w (Numpy array): real wage rate
        r (Numpy array): real interest rate on household portfolio
        BQ (array_like): aggregate bequest amounts
        TR (Numpy array): lump sum transfer amount
        theta (Numpy array): retirement replacement rates, length J
        initial_values (tuple): initial period variable values,
            (b_sinit, b_splus1init, factor, initial_b, initial_n,
            D0_baseline)
        j (int): index of ability type
        ind (Numpy array): integers from 0 to S-1
        p (OG-USA Specifications object): model parameters

    Returns:
        (tuple): household solution results:

            * euler_errors (Numpy array): errors from FOCs, size = Tx2S
            * b_mat (Numpy array): savings amounts, size = TxS
            * n_mat (Numpy array): labor supply amounts, size = TxS

    '''
    # unpack variables and parameters pass to function
    (K0, b_sinit, b_splus1init, factor, initial_b, initial_n) =\
        initial_values
    guesses_b, guesses_n = guesses
    r, w, r_hh, BQ, TR, theta = outer_loop_vars

    # compute w
    w[:p.T] = firm.get_w_from_r(r[:p.T], p, 'TPI')
    # compute bq
    bq = household.get_bq(BQ, None, p, 'TPI')
    # compute tr
    tr = household.get_tr(TR, None, p, 'TPI')

    # initialize arrays
    b_mat = np.zeros((p.T + p.S, p.S))
    n_mat = np.zeros((p.T + p.S, p.S))
    euler_errors = np.zeros((p.T, 2 * p.S))

    b_mat[0, -1], n_mat[0, -1] =\
        np.array(opt.fsolve(firstdoughnutring, [guesses_b[0, -1],
                                                guesses_n[0, -1]],
                            args=(r_hh[0], w[0], bq[0, -1, j],
                                  tr[0, -1, j],
                                  theta * p.replacement_rate_adjust[0],
                                  factor, j, initial_b, p),
                            xtol=MINIMIZER_TOL))

    for s in range(p.S - 2):  # Upper triangle
        ind2 = np.arange(s + 2)
        b_guesses_to_use = np.diag(guesses_b[:p.S, :], p.S - (s + 2))
        n_guesses_to_use = np.diag(guesses_n[:p.S, :], p.S - (s + 2))
        theta_to_use = theta[j] * p.replacement_rate_adjust[:p.S]
        bq_to_use = np.diag(bq[:p.S, :, j], p.S - (s + 2))
        tr_to_use = np.diag(tr[:p.S, :, j], p.S - (s + 2))
        tau_c_to_use = np.diag(p.tau_c[:p.S, :, j], p.S - (s + 2))

        length_diag =\
            np.diag(p.etr_params[:p.S, :, 0], p.S-(s + 2)).shape[0]
        etr_params_to_use = np.zeros((length_diag, p.etr_params.shape[2]))
        mtrx_params_to_use = np.zeros((length_diag, p.mtrx_params.shape[2]))
        mtry_params_to_use = np.zeros((length_diag, p.mtry_params.shape[2]))
        for i in range(p.etr_params.shape[2]):
            etr_params_to_use[:, i] =\
                np.diag(p.etr_params[:p.S, :, i], p.S - (s + 2))
            mtrx_params_to_use[:, i] =\
                np.diag(p.mtrx_params[:p.S, :, i], p.S - (s + 2))
            mtry_params_to_use[:, i] =\
                np.diag(p.mtry_params[:p.S, :, i], p.S - (s + 2))

        solutions = opt.fsolve(twist_doughnut,
                               list(b_guesses_to_use) +
                               list(n_guesses_to_use),
                               args=(r_hh, w, bq_to_use, tr_to_use,
                                     theta_to_use, factor, j, s, 0,
                                     tau_c_to_use,
                                     etr_params_to_use,
                                     mtrx_params_to_use,
                                     mtry_params_to_use, initial_b, p),
                               xtol=MINIMIZER_TOL)

        b_vec = solutions[:int(len(solutions) / 2)]
        b_mat[ind2, p.S - (s + 2) + ind2] = b_vec
        n_vec = solutions[int(len(solutions) / 2):]
        n_mat[ind2, p.S - (s + 2) + ind2] = n_vec

    for t in range(0, p.T):
        b_guesses_to_use = .75 * \
            np.diag(guesses_b[t:t + p.S, :])
        n_guesses_to_use = np.diag(guesses_n[t:t + p.S, :])
        theta_to_use = theta[j] * p.replacement_rate_adjust[t:t + p.S]
        bq_to_use = np.diag(bq[t:t + p.S, :, j])
        tr_to_use = np.diag(tr[t:t + p.S, :, j])
        tau_c_to_use = np.diag(p.tau_c[t:t + p.S, :, j])

        # initialize array of diagonal elements
        etr_params_TP = np.zeros((p.T + p.S, p.S,  p.etr_params.shape[2]))
        etr_params_TP[:p.T, :, :] = p.etr_params
        etr_params_TP[p.T:, :, :] = p.etr_params[-1, :, :]

        mtrx_params_TP = np.zeros((p.T + p.S, p.S,  p.mtrx_params.shape[2]))
        mtrx_params_TP[:p.T, :, :] = p.mtrx_params
        mtrx_params_TP[p.T:, :, :] = p.mtrx_params[-1, :, :]

        mtry_params_TP = np.zeros((p.T + p.S, p.S,  p.mtry_params.shape[2]))
        mtry_params_TP[:p.T, :, :] = p.mtry_params
        mtry_params_TP[p.T:, :, :] = p.mtry_params[-1, :, :]

        length_diag =\
            np.diag(etr_params_TP[t:t + p.S, :, 0]).shape[0]
        etr_params_to_use = np.zeros((length_diag, p.etr_params.shape[2]))
        mtrx_params_to_use = np.zeros((length_diag, p.mtrx_params.shape[2]))
        mtry_params_to_use = np.zeros((length_diag, p.mtry_params.shape[2]))

        for i in range(p.etr_params.shape[2]):
            etr_params_to_use[:, i] = np.diag(etr_params_TP[t:t + p.S, :, i])
            mtrx_params_to_use[:, i] = np.diag(mtrx_params_TP[t:t + p.S, :, i])
            mtry_params_to_use[:, i] = np.diag(mtry_params_TP[t:t + p.S, :, i])

        [solutions, infodict, ier, message] =\
            opt.fsolve(twist_doughnut, list(b_guesses_to_use) +
                       list(n_guesses_to_use),
                       args=(r_hh, w, bq_to_use, tr_to_use,
                             theta_to_use, factor,
                             j, None, t, tau_c_to_use,
                             etr_params_to_use, mtrx_params_to_use,
                             mtry_params_to_use, initial_b, p),
                       xtol=MINIMIZER_TOL, full_output=True)
        euler_errors[t, :] = infodict['fvec']

        b_vec = solutions[:p.S]
        b_mat[t + ind, ind] = b_vec
        n_vec = solutions[p.S:]
        n_mat[t + ind, ind] = n_vec

    print('Type ', j, ' max euler error = ',
          np.absolute(euler_errors).max())

    return euler_errors, b_mat, n_mat


def run_TPI(p, client=None):
    '''
    Solve for transition path equilibrium of OG-USA.

    Args:
        p (OG-USA Specifications object): model parameters
        client (Dask client object): client

    Returns:
        output (dictionary): dictionary with transition path solution
            results

    '''
    # unpack tuples of parameters
    initial_values, ss_vars, theta, baseline_values = get_initial_SS_values(p)
    (B0, b_sinit, b_splus1init, factor, initial_b, initial_n) =\
        initial_values
    (TRbaseline, Gbaseline, D0_baseline) = baseline_values

    print('Government spending breakpoints are tG1: ', p.tG1,
          '; and tG2:', p.tG2)

    # Initialize guesses at time paths
    if p.baseline:

        # Make array of initial guesses for labor supply and savings
        guesses_b = utils.get_initial_path(
            initial_b, ss_vars['bssmat_splus1'], p, 'ratio')
        guesses_n = utils.get_initial_path(
            initial_n, ss_vars['nssmat'], p, 'ratio')
        b_mat = guesses_b
        n_mat = guesses_n
        ind = np.arange(p.S)

        # Get path for aggregate savings and labor supply`
        L_init = np.ones((p.T + p.S,)) * ss_vars['Lss']
        B_init = np.ones((p.T + p.S,)) * ss_vars['Bss']
        L_init[:p.T] = aggr.get_L(n_mat[:p.T], p, 'TPI')
        B_init[1:p.T] = aggr.get_B(b_mat[:p.T], p, 'TPI', False)[:p.T - 1]
        B_init[0] = B0
        K_init = B_init * ss_vars['Kss'] / ss_vars['Bss']
        K = K_init
        K_d = K_init * ss_vars['K_d_ss'] / ss_vars['Kss']
        K_f = K_init * ss_vars['K_f_ss'] / ss_vars['Kss']
        L = L_init
        B = B_init
        Y = np.zeros_like(K)
        Y[:p.T] = firm.get_Y(K[:p.T], L[:p.T], p, 'TPI')
        Y[p.T:] = ss_vars['Yss']
        r = np.zeros_like(Y)
        r[:p.T] = firm.get_r(Y[:p.T], K[:p.T], p, 'TPI')
        r[p.T:] = ss_vars['rss']
        # For case where economy is small open econ
        r[p.zeta_K == 1] = p.world_int_rate[p.zeta_K == 1]
        # Compute other interest rates
        r_gov = fiscal.get_r_gov(r, p)
        r_hh = aggr.get_r_hh(r, r_gov, K, ss_vars['Dss'])

        # compute w
        w = np.zeros_like(r)
        w[:p.T] = firm.get_w_from_r(r[:p.T], p, 'TPI')
        w[p.T:] = ss_vars['wss']

        # initial guesses at fiscal vars
        if p.budget_balance:
            if np.abs(ss_vars['TR_ss']) < 1e-13:
                TR_ss2 = 0.0  # sometimes SS is very small but not zero,
                # even if taxes are zero, this get's rid of the
                # approximation error, which affects the pct changes below
            else:
                TR_ss2 = ss_vars['TR_ss']
            TR = np.ones(p.T + p.S) * TR_ss2
            total_tax_revenue = TR - ss_vars['agg_pension_outlays']
            G = np.zeros(p.T + p.S)
            D = np.zeros(p.T + p.S)
            D_d = np.zeros(p.T + p.S)
            D_f = np.zeros(p.T + p.S)
        else:
            if p.baseline_spending:
                TR = TRbaseline
                G = Gbaseline
                G[p.T:] = ss_vars['Gss']
            else:
                TR = p.alpha_T * Y
                G = np.ones(p.T + p.S) * ss_vars['Gss']
            D = np.ones(p.T + p.S) * ss_vars['Dss']
            D_d = D * ss_vars['D_d_ss'] / ss_vars['Dss']
            D_f = D * ss_vars['D_f_ss'] / ss_vars['Dss']
        total_tax_revenue = np.ones(p.T + p.S) * ss_vars['total_tax_revenue']

        # Initialize bequests
        BQ0 = aggr.get_BQ(r_hh[0], initial_b, None, p, 'SS', True)
        if not p.use_zeta:
            BQ = np.zeros((p.T + p.S, p.J))
            for j in range(p.J):
                BQ[:, j] = (
                    list(np.linspace(BQ0[j], ss_vars['BQss'][j], p.T)) +
                    [ss_vars['BQss'][j]] * p.S)
            BQ = np.array(BQ)
        else:
            BQ = (list(np.linspace(BQ0, ss_vars['BQss'], p.T)) +
                [ss_vars['BQss']] * p.S)
            BQ = np.array(BQ)
    else:
        # Use the baseline solution to get starting values for the reform
        baseline_tpi_path = os.path.join(
            p.baseline_dir, 'TPI', 'TPI_vars.pkl')
        tpi_solutions = utils.safe_read_pickle(baseline_tpi_path)
        # use baseline solution as starting values if dimensions match
        if tpi_solutions['bmat_splus1'].shape == (p.T, p.S, p.J):
            (L, B, K, K_d, K_f, Y, r, r_gov, r_hh, w, TR, G, D, D_d,
             D_f, total_tax_revenue, BQ, guesses_b, guesses_n) =\
                (tpi_solutions['L'], tpi_solutions['B'],
                 tpi_solutions['K'], tpi_solutions['K_d'],
                 tpi_solutions['K_f'], tpi_solutions['Y'],
                 tpi_solutions['r'], tpi_solutions['r_gov'],
                 tpi_solutions['r_hh'], tpi_solutions['w'],
                 tpi_solutions['TR'], tpi_solutions['G'],
                 tpi_solutions['D'], tpi_solutions['D_d'],
                 tpi_solutions['D_f'], tpi_solutions['total_tax_revenue'],
                 tpi_solutions['BQ'], tpi_solutions['bmat_splus1'],
                 tpi_solutions['n_mat'])
            # extend n and bsplus1 arrays so T+S years long
            b_tail = np.tile(ss_vars['bssmat_splus1'].reshape(1, p.S, p.J),
                             (p.S, 1, 1))
            n_tail = np.tile(ss_vars['nssmat'].reshape(1, p.S, p.J),
                             (p.S, 1, 1))
            guesses_b = np.append(guesses_b, b_tail, axis=0)
            guesses_n = np.append(guesses_n, n_tail, axis=0)

    TPIiter = 0
    TPIdist = 10
    euler_errors = np.zeros((p.T, 2 * p.S, p.J))
    TPIdist_vec = np.zeros(p.maxiter)

    # TPI loop
    while (TPIiter < p.maxiter) and (TPIdist >= p.mindist_TPI):
        r_gov[:p.T] = fiscal.get_r_gov(r[:p.T], p)
        if not p.budget_balance:
            K[:p.T] = firm.get_K_from_Y(Y[:p.T], r[:p.T], p, 'TPI')

        r_hh[:p.T] = aggr.get_r_hh(r[:p.T], r_gov[:p.T], K[:p.T],
                                   D[:p.T])

        outer_loop_vars = (r, w, r_hh, BQ, TR, theta)

        euler_errors = np.zeros((p.T, 2 * p.S, p.J))
        lazy_values = []
        for j in range(p.J):
            guesses = (guesses_b[:, :, j], guesses_n[:, :, j])
            lazy_values.append(
                delayed(inner_loop)(guesses, outer_loop_vars,
                                    initial_values, j, ind, p))
        if client:
            futures = client.compute(lazy_values,
                                     num_workers=p.num_workers)
            results = client.gather(futures)
        else:
            results = results = compute(
                *lazy_values, scheduler=dask.multiprocessing.get,
                num_workers=p.num_workers)

        for j, result in enumerate(results):
            euler_errors[:, :, j], b_mat[:, :, j], n_mat[:, :, j] = result

        bmat_s = np.zeros((p.T, p.S, p.J))
        bmat_s[0, 1:, :] = initial_b[:-1, :]
        bmat_s[1:, 1:, :] = b_mat[:p.T-1, :-1, :]
        bmat_splus1 = np.zeros((p.T, p.S, p.J))
        bmat_splus1[:, :, :] = b_mat[:p.T, :, :]

        etr_params_4D = np.tile(
            p.etr_params.reshape(p.T, p.S, 1, p.etr_params.shape[2]),
            (1, 1, p.J, 1))
        bqmat = household.get_bq(BQ, None, p, 'TPI')
        trmat = household.get_tr(TR, None, p, 'TPI')
        tax_mat = tax.net_taxes(
            r_hh[:p.T], w[:p.T], bmat_s, n_mat[:p.T, :, :],
            bqmat[:p.T, :, :], factor, trmat[:p.T, :, :], theta, 0,
            None, False, 'TPI', p.e, etr_params_4D, p)
        r_hh_path = utils.to_timepath_shape(r_hh)
        wpath = utils.to_timepath_shape(w)
        c_mat = household.get_cons(r_hh_path[:p.T, :, :], wpath[:p.T, :, :],
                                   bmat_s, bmat_splus1,
                                   n_mat[:p.T, :, :], bqmat[:p.T, :, :],
                                   tax_mat, p.e, p.tau_c[:p.T, :, :], p)
        y_before_tax_mat = household.get_y(
            r_hh_path[:p.T, :, :], wpath[:p.T, :, :],
            bmat_s[:p.T, :, :], n_mat[:p.T, :, :], p)

        (total_tax_rev, iit_payroll_tax_revenue,
         agg_pension_outlays, bequest_tax_revenue, wealth_tax_revenue,
         cons_tax_revenue, business_tax_revenue, payroll_tax_revenue,
         iit_revenue) = aggr.revenue(
                r_hh[:p.T], w[:p.T], bmat_s, n_mat[:p.T, :, :],
                bqmat[:p.T, :, :], c_mat[:p.T, :, :], Y[:p.T],
                L[:p.T], K[:p.T], factor, theta, etr_params_4D,
                p, 'TPI')
        total_tax_revenue[:p.T] = total_tax_rev
        dg_fixed_values = (Y, total_tax_revenue, agg_pension_outlays,
                           TR, Gbaseline, D0_baseline)
        (Dnew, G[:p.T], D_d[:p.T], D_f[:p.T], new_borrowing,
         debt_service, new_borrowing_f) =\
            fiscal.D_G_path(r_gov, dg_fixed_values, p)
        L[:p.T] = aggr.get_L(n_mat[:p.T], p, 'TPI')
        B[1:p.T] = aggr.get_B(bmat_splus1[:p.T], p, 'TPI',
                              False)[:p.T - 1]
        K_demand_open = firm.get_K(
            L[:p.T], p.world_int_rate[:p.T], p, 'TPI')
        K[:p.T], K_d[:p.T], K_f[:p.T] = aggr.get_K_splits(
            B[:p.T], K_demand_open, D_d[:p.T], p.zeta_K[:p.T])
        Ynew = firm.get_Y(K[:p.T], L[:p.T], p, 'TPI')
        rnew = r.copy()
        rnew[:p.T] = firm.get_r(Ynew[:p.T], K[:p.T], p, 'TPI')
        # For case where economy is small open econ
        r[p.zeta_K == 1] = p.world_int_rate[p.zeta_K == 1]
        r_gov_new = fiscal.get_r_gov(rnew, p)
        r_hh_new = aggr.get_r_hh(rnew[:p.T], r_gov_new[:p.T], K[:p.T],
                                 Dnew[:p.T])
        # compute w
        wnew = firm.get_w_from_r(rnew[:p.T], p, 'TPI')

        b_mat_shift = np.append(np.reshape(initial_b, (1, p.S, p.J)),
                                b_mat[:p.T - 1, :, :], axis=0)
        BQnew = aggr.get_BQ(r_hh_new[:p.T], b_mat_shift, None, p,
                            'TPI', False)
        bqmat_new = household.get_bq(BQnew, None, p, 'TPI')
        (total_tax_rev, iit_payroll_tax_revenue,
         agg_pension_outlays, bequest_tax_revenue, wealth_tax_revenue,
         cons_tax_revenue, business_tax_revenue, payroll_tax_revenue,
         iit_revenue) = aggr.revenue(
                r_hh_new[:p.T], wnew[:p.T], bmat_s, n_mat[:p.T, :, :],
                bqmat_new[:p.T, :, :], c_mat[:p.T, :, :], Ynew[:p.T],
                L[:p.T], K[:p.T], factor, theta, etr_params_4D, p, 'TPI')
        total_tax_revenue[:p.T] = total_tax_rev
        TR_new = fiscal.get_TR(
            Ynew[:p.T], TR[:p.T], G[:p.T], total_tax_revenue[:p.T],
            agg_pension_outlays[:p.T], p, 'TPI')

        # update vars for next iteration
        w[:p.T] = wnew[:p.T]
        r[:p.T] = utils.convex_combo(rnew[:p.T], r[:p.T], p.nu)
        BQ[:p.T] = utils.convex_combo(BQnew[:p.T], BQ[:p.T], p.nu)
        D[:p.T] = Dnew[:p.T]
        Y[:p.T] = utils.convex_combo(Ynew[:p.T], Y[:p.T], p.nu)
        if not p.baseline_spending:
            TR[:p.T] = utils.convex_combo(TR_new[:p.T], TR[:p.T], p.nu)
        guesses_b = utils.convex_combo(b_mat, guesses_b, p.nu)
        guesses_n = utils.convex_combo(n_mat, guesses_n, p.nu)
        print('r diff: ', (rnew[:p.T] - r[:p.T]).max(),
              (rnew[:p.T] - r[:p.T]).min())
        print('BQ diff: ', (BQnew[:p.T] - BQ[:p.T]).max(),
              (BQnew[:p.T] - BQ[:p.T]).min())
        print('TR diff: ', (TR_new[:p.T]-TR[:p.T]).max(),
              (TR_new[:p.T] - TR[:p.T]).min())
        print('Y diff: ', (Ynew[:p.T]-Y[:p.T]).max(),
              (Ynew[:p.T] - Y[:p.T]).min())
        if not p.baseline_spending:
            if TR.all() != 0:
                TPIdist = np.array(
                    list(utils.pct_diff_func(rnew[:p.T], r[:p.T])) +
                    list(utils.pct_diff_func(BQnew[:p.T],
                                             BQ[:p.T]).flatten()) +
                    list(utils.pct_diff_func(TR_new[:p.T],
                                             TR[:p.T]))).max()
            else:
                TPIdist = np.array(
                    list(utils.pct_diff_func(rnew[:p.T], r[:p.T])) +
                    list(utils.pct_diff_func(BQnew[:p.T],
                                             BQ[:p.T]).flatten()) +
                    list(np.abs(TR[:p.T]))).max()
        else:
            TPIdist = np.array(
                list(utils.pct_diff_func(rnew[:p.T], r[:p.T])) +
                list(utils.pct_diff_func(BQnew[:p.T], BQ[:p.T]).flatten())
                + list(utils.pct_diff_func(Ynew[:p.T], Y[:p.T]))).max()

        TPIdist_vec[TPIiter] = TPIdist
        # After T=10, if cycling occurs, drop the value of nu
        # wait til after T=10 or so, because sometimes there is a jump up
        # in the first couple iterations
        # if TPIiter > 10:
        #     if TPIdist_vec[TPIiter] - TPIdist_vec[TPIiter - 1] > 0:
        #         nu /= 2
        #         print 'New Value of nu:', nu
        TPIiter += 1
        print('Iteration:', TPIiter)
        print('\tDistance:', TPIdist)

    # Compute effective and marginal tax rates for all agents
    mtrx_params_4D = np.tile(
        p.mtrx_params.reshape(p.T, p.S, 1, p.mtrx_params.shape[2]),
        (1, 1, p.J, 1))
    mtry_params_4D = np.tile(
        p.mtry_params.reshape(p.T, p.S, 1, p.mtry_params.shape[2]),
        (1, 1, p.J, 1))

    e_3D = np.tile(p.e.reshape(1, p.S, p.J), (p.T, 1, 1))
    mtry_path = tax.MTR_income(r_hh_path[:p.T], wpath[:p.T],
                               bmat_s[:p.T, :, :],
                               n_mat[:p.T, :, :], factor, True,
                               e_3D, etr_params_4D, mtry_params_4D, p)
    mtrx_path = tax.MTR_income(r_hh_path[:p.T], wpath[:p.T],
                               bmat_s[:p.T, :, :],
                               n_mat[:p.T, :, :], factor, False,
                               e_3D, etr_params_4D, mtrx_params_4D, p)
    etr_path = tax.ETR_income(r_hh_path[:p.T], wpath[:p.T],
                              bmat_s[:p.T, :, :],
                              n_mat[:p.T, :, :], factor, e_3D,
                              etr_params_4D, p)

    C = aggr.get_C(c_mat, p, 'TPI')
    # Note that implicity in this computation is that immigrants'
    # wealth is all in the form of private capital
    I_d = aggr.get_I(bmat_splus1[:p.T], K_d[1:p.T + 1], K_d[:p.T], p,
                     'TPI')
    I = aggr.get_I(bmat_splus1[:p.T], K[1:p.T + 1], K[:p.T], p, 'TPI')
    # solve resource constraint
    # foreign debt service costs
    debt_service_f = fiscal.get_debt_service_f(r_hh, D_f)
    RC_error = aggr.resource_constraint(
        Y[:p.T - 1], C[:p.T - 1], G[:p.T - 1], I_d[:p.T - 1],
        K_f[:p.T - 1], new_borrowing_f[:p.T - 1],
        debt_service_f[:p.T - 1], r_hh[:p.T - 1], p)
    # Compute total investment (not just domestic)
    I_total = aggr.get_I(None, K[1:p.T + 1], K[:p.T], p, 'total_tpi')

    # Compute resource constraint error
    rce_max = np.amax(np.abs(RC_error))
    print('Max absolute value resource constraint error:', rce_max)

    print('Checking time path for violations of constraints.')
    for t in range(p.T):
        household.constraint_checker_TPI(
            b_mat[t], n_mat[t], c_mat[t], t, p.ltilde)

    eul_savings = euler_errors[:, :p.S, :].max(1).max(1)
    eul_laborleisure = euler_errors[:, p.S:, :].max(1).max(1)

    print('Max Euler error, savings: ', eul_savings)
    print('Max Euler error labor supply: ', eul_laborleisure)

    '''
    ------------------------------------------------------------------------
    Save variables/values so they can be used in other modules
    ------------------------------------------------------------------------
    '''

    output = {'Y': Y[:p.T], 'B': B, 'K': K, 'K_f': K_f, 'K_d': K_d,
              'L': L, 'C': C, 'I': I,
              'I_total': I_total, 'I_d': I_d, 'BQ': BQ,
              'total_tax_revenue': total_tax_revenue,
              'business_tax_revenue': business_tax_revenue,
              'iit_payroll_tax_revenue': iit_payroll_tax_revenue,
              'iit_revenue': iit_revenue,
              'payroll_tax_revenue': payroll_tax_revenue, 'TR': TR,
              'agg_pension_outlays': agg_pension_outlays,
              'bequest_tax_revenue': bequest_tax_revenue,
              'wealth_tax_revenue': wealth_tax_revenue,
              'cons_tax_revenue': cons_tax_revenue, 'G': G, 'D': D,
              'D_f': D_f, 'D_d': D_d, 'r': r, 'r_gov': r_gov,
              'r_hh': r_hh, 'w': w, 'bmat_splus1': bmat_splus1,
              'bmat_s': bmat_s[:p.T, :, :], 'n_mat': n_mat[:p.T, :, :],
              'c_path': c_mat, 'bq_path': bqmat, 'tr_path': trmat,
              'y_before_tax_mat': y_before_tax_mat,
              'tax_path': tax_mat, 'eul_savings': eul_savings,
              'eul_laborleisure': eul_laborleisure,
              'resource_constraint_error': RC_error,
              'new_borrowing_f': new_borrowing_f,
              'debt_service_f': debt_service_f,
              'etr_path': etr_path, 'mtrx_path': mtrx_path,
              'mtry_path': mtry_path}

    tpi_dir = os.path.join(p.output_base, "TPI")
    utils.mkdirs(tpi_dir)
    tpi_vars = os.path.join(tpi_dir, "TPI_vars.pkl")
    with open(tpi_vars, "wb") as f:
        pickle.dump(output, f)

    if np.any(G) < 0:
        print('Government spending is negative along transition path' +
              ' to satisfy budget')

    if (((TPIiter >= p.maxiter) or
            (np.absolute(TPIdist) > p.mindist_TPI)) and
            ENFORCE_SOLUTION_CHECKS):
        raise RuntimeError('Transition path equlibrium not found' +
                           ' (TPIdist)')

    if ((np.any(np.absolute(RC_error) >= p.mindist_TPI * 10)) and
            ENFORCE_SOLUTION_CHECKS):
        raise RuntimeError('Transition path equlibrium not found ' +
                           '(RC_error)')

    if ((np.any(np.absolute(eul_savings) >= p.mindist_TPI) or
            (np.any(np.absolute(eul_laborleisure) > p.mindist_TPI))) and
            ENFORCE_SOLUTION_CHECKS):
        raise RuntimeError('Transition path equlibrium not found ' +
                           '(eulers)')

    return output
