(Chap_Firms)=
# Trade


## Export Demand
When the `OG-Core` model is parameterized as an open economy, the balance of payments is modeled.

Export demand is modeled as a fixed fraction of domestic demand for each production good. Total demand for output from industry $m$ ($m<M$) is given as:

$Y^{demand}_{m,t} = C_{m,t} + G_{m,t}+ C^f_{m,t}$

Where $C^f_{m,t}$ is foreign demand for industry $m$ output and is given by:

$$
C^f_{m,t} = \alpha^{f}_{m,t}C_{m,t}
$$

The parameter $\alpha^{f}_{m,t}$ represents foreign demand as  (potentially time varying) exogenous proportion of domestic demand.  While this is a simplification in the specification of export demand, it does have the nice property of having export demand move with domestic demand. So if the price of output from industry $m$ falls and thereby increases domestic demand, foreign demand for industry $m$ output will also increase.

For industry $M$, which is the capital producing industry, the demand for output is given by:

$Y^{demand}_{M,t} = C_{M,t} + I_{M,t} + I_{g,t} + G_{M,t} + C^f_{M,t}$

$I_{M,t}$ is demand for domestically produced investment goods:

$$
I_{M,t} = K^d_{t+1} - (1 - \delta_{M,t})K^d_t
$$

Where $C^f_{M,t}$ is foreign demand for industry $M$ output and is given by:

$$
C^f_{M,t} = \alpha^{f}_{M,t}(C_{M,t} + I_{M,t})
$$

Total export demand in units of the numeraire good is thus given as:

$EX = \sum_{m=1}^{M} p_{m,t}C^f_{m,t}$

## Import Demand

Import demand is modeled as the fraction of domestic demand for each consumption good that comes from abroad. In the fixed coefficient matrix $\Pi$, the last column represents the fraction of that consumption good that is produced from outside the country.  For good $i$, denote this share as $\pi_{i,ROW}$.

Total imports are thus given by:

$IM = \sum_{i=1}^{I} \pi_{i,ROW}p_{i,t}C_{i,t}$

Note that in the above formulation of imports, we assume that that the law of on price holds and therefore that the price of good $i$ from the rest of the world is equivalent to the price of good $i$ produced domestically.


## Trade Balance

The trade balances is given by $NX = EX - IM$.

## Current account

The current account consists of the trade balance plus investment income plus foreign transfers.

$CA = NX - r_{p,t} K^f_t - r_{p,t}D^f_t$



## Capital account

Flows of financial capital into and out of the country.

$KA = (K^f_{t+1} - K^f_t) - \bigl(D^f_{t+1} - D^f_t\bigr)$


## Balance of payments

The balance of payments requires that the current account plus the capital account equal zero.

$CA + KA = 0$

Or

$$
\sum_{m=1}^{M} p_{m,t}C^f_{m,t} -  \sum_{i=1}^{I} \pi_{i,ROW}p_{i,t}C_{i,t} - r_{p,t} K^f_t - r_{p,t}D^f_t = (K^f_{t+1} - K^f_t) - \bigl(D^f_{t+1} - D^f_t\bigr)
$$