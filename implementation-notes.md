# Calculator equation mapping and validation — 2026-10-07

Source: handwritten equations in [4sbb-equations.pdf](4sbb-equations.pdf), pages 1–11.

Local inspection: the original calculator was a comment-only outline; no local calculator examples or capsule configuration were present. Python 3.13.7, Matplotlib 3.10.8 and NumPy are installed.

Supported plotting workflow: `pyplot.subplots`, axes `plot`, figure `savefig`, then `pyplot.show`; documented by [Matplotlib](https://matplotlib.org/3.10.8/api/_as_gen/matplotlib.pyplot.subplots.html). Simulation uses a bounded fixed-step RK4 integration of the user's averaged CCM equations, separately from the analytical design calculations. It is an ideal open-loop model, without control, switching ripple, dead time, saturation or losses.

General averaged equations: di/dt = (DA Vin − DB v)/L; dv/dt = (DB i − v/R)/C. Buck: DA = Vout/Vin, DB = 1. Boost: DA = 1, DB = Vin/Vout; the boost low-side duty D = 1 − DB. Transition: choose DB = transition_duty, DA = DB Vout/Vin, and phase-shift output PWM to create nonzero instantaneous inductor voltage at unity conversion. Both duties must remain in [0, 1].

Apparent handwritten typos are corrected explicitly: page 2 boost ripple is Vin D/(L fs), consistent with VL,on = Vin and the page's inductance equation; page 8 pull-down power is Vgs²/R, consistent with I = Vgs/R. [TI LM5176 datasheet](https://www.ti.com/lit/ds/symlink/lm5176.pdf), sections 8.2.2.4–8.2.2.6, supports the boost ripple and pulsed capacitor relationships. The calculator retains the notes' first-order design approximations. Transition/input boost capacitor quantities are derived from the selected piecewise PWM waveform because the notes do not provide those equations.

Plausible implementation failures: confusing DB with boost low-side duty; using boost IL = Iout; doubling body-diode loss across devices; treating all four devices as switching in buck/boost; counting gate energy twice; assuming equal duties imply zero ripple despite phase shift; entering micro-units as SI; numerically unstable simulation time steps.

Smallest diagnostic before simulation: evaluate duties and analytical steady-state currents, then check both averaged derivatives are zero at equilibrium in all three modes. Verify buck/boost ripple against VL Δt/L. Only then integrate and plot. Success requires equilibrium residuals near zero, RK4 convergence with halved step size, and finite trajectories approaching the predicted equilibrium. Validate CLI defaults, invalid input handling, and headless plot saving separately.

All component/driver/thermal defaults are illustrative and require replacement with measured or datasheet values at the actual operating point. Missing Steinmetz inputs leave core loss unavailable; total loss and efficiency are then labeled partial estimates. The averaged simulation does not certify hardware operation or a controller design.

## Completed verification

On 2026-10-07, all 10 checks in `test_calculator.py` passed: equilibrium and power balance across buck/boost/transition; volt-time ripple and RMS checks; phase-dependent transition ripple; capacitor equations; switching-device and diode accounting; load/core inputs and power balance; shared-sink thermal calculation; RK4 step refinement and settling; invalid constants/ESR limits; interactive CSV and CLI rejection. Command: `python -m unittest discover -s breadboard-4sbb -p 'test_*.py' -v`.

Then `python breadboard-4sbb/4sbb-calculator.py --defaults --no-show` saved `state-space.png` and `state-space-sweep.png`. Both saved images were visually inspected for axes, units, mode labels and finite trajectories. `example-results.txt` contains this illustrative run. (Those figures used the earlier illustrative defaults and are superseded below.)

## Losses and switched simulation — 2026-10-07

The earlier averaged plots were lossless. 557 µH with 100 µF and 30 Ω gives an L–Cout resonance near 600 Hz with Q ≈ 13. That ringing looked like ripple but is not switching ripple. Changes:

- Defaults now use IRFP260NPBF datasheet values and the measured coil: DCR 1.19 Ω from Rs at 20 Hz, and AC resistance 18.8 Ω from Rs at 50 kHz, applied to the ripple RMS current.
- The averaged model includes Rs = DCR + 2·Rds,hot = 1.31 Ω, which gives ζ ≈ 0.3.
- `regulated_duties` solves for the duties that hold Vout under that drop (buck/transition: DA; boost: quadratic in DB).
- `simulate_switching` solves the periodic steady state x(T) = x(0) of the piecewise-linear switched circuit with exact matrix exponentials (`affine_flow`, scaling and squaring).

Defaults at Vin = Vout = 30 V, 30 Ω, 50 kHz (transition, DB = 0.7):

| Quantity | Analytical | Switched simulation |
|---|---:|---:|
| Inductor ripple (ideal duties, lossless) | 0.3232 App | 0.3233 App |
| Output ripple (cap + ESR) | 0.0918 Vpp | 0.0852 Vpp |

With losses, the regulated duties are DA = 0.762, DB = 0.700. Inductor ripple is 0.303 App, which is 21% of the 1.43 A average and below the 0.43 App target. Coil copper loss is 2.72 W (2.43 W DC, 0.29 W AC ripple), the largest single loss. Estimated efficiency is 83.6%, excluding core loss (air core), reverse recovery and wiring.

The Rs·IL drop (about 1.3–1.9 V) exceeds the 0.5 V transition window. Buck operation just above 30.5 V therefore cannot reach 30 V, and the calculator warns. Widen `transition_window` to about 2 V, or start buck only once DA ≤ 1 with losses.

Verification: `python -m unittest discover -p 'test_*.py'` ran 12 tests, all OK. The new tests check:

- Switched ripple and average against the analytical values in all three modes, plus Vout ripple in buck.
- Regulated-duty equilibria with series resistance.
- Averaged settling to the lossy equilibrium.
- Rejection of an unreachable Vin.

`python 4sbb-calculator.py --defaults --no-show` regenerated `example-results.txt`, `state-space.png`, `state-space-sweep.png` and `state-space-switching.png`. All three images were visually inspected.
