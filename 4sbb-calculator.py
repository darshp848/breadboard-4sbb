"""4-switch buck-boost calculator using 4sbb-equations.pdf (SI units).

python 4sbb-calculator.py                        # CSV prompts, print, pyplot
python 4sbb-calculator.py --defaults --no-show   # illustrative example, save plots
python 4sbb-calculator.py --defaults --set vout=24 --set fs=100000

DA/DB are input/output HIGH-SIDE duties. Boost low-side duty D = 1-DB.
See implementation-notes.md for equation provenance and corrections.
"""
import argparse
from dataclasses import dataclass, fields, replace
import math
from pathlib import Path
import numpy as np


@dataclass(frozen=True)
class Constants:
    # Page 1 bench targets. FET values: IRFP260NPBF datasheet (max where given).
    # Gate supply: one MER1S0515SC (15 V, 1 W) per FET. Isolated driver part is
    # unknown, so driver resistances/delays/Iq remain EXAMPLES.
    vin: float = 30.0
    vout: float = 30.0
    pout: float = 30.0
    supply_current_limit: float = 5.0
    fs: float = 50e3
    inductance: float = 557e-6
    cin: float = 100e-6
    cout: float = 100e-6
    load_resistance: float | None = None  # Default Vout^2/Pout.
    vin_min: float = 10.0
    vin_max: float = 30.0
    transition_window: float = 0.5
    transition_duty: float = 0.7  # DB; DA is adjusted to balance volt-seconds.
    phase_shift: float = 0.5  # Output PWM offset, in switching periods.
    target_ripple_fraction: float = 0.3
    saturation_margin: float = 1.5
    allowed_input_ripple: float = 0.3
    allowed_output_ripple: float = 0.3
    inductor_dcr: float = 1.19  # Measured air-core coil Rs at 20 Hz.
    inductor_ac_resistance: float | None = 18.8  # Coil Rs at fs (50 kHz, 1 V).
    cin_esr: float = 0.02
    cout_esr: float = 0.02
    rds_on_25: float = 0.040  # Max at Vgs=10 V.
    rds_hot_factor: float = 1.5
    coss: float = 603e-12  # Typ at Vds=25 V.
    eoss: float | None = None  # If supplied, replaces 0.5*Coss*Vds^2.
    qg: float = 234e-9  # Max at Vgs=10 V; higher at 15 V drive.
    qgd: float = 110e-9
    vdrive: float = 15.0
    vplateau: float = 5.0  # Read from Qg curve; rises with drain current.
    driver_source_resistance: float = 2.0
    driver_sink_resistance: float = 2.0
    gate_internal_resistance: float = 1.0
    gate_external_resistance: float = 10.0
    desired_miller_time: float = 100e-9
    driver_quiescent_current: float = 2e-3  # Per half-bridge driver; two drivers.
    gate_power_available: float = 1.0  # Per-FET isolated gate supply budget.
    gate_pulldown_resistance: float = 10e3
    diode_vf: float = 1.3
    dead_time: float = 500e-9  # 0.5-2 us suggested for first tests.
    turnoff_delay: float = 55e-9
    delay_mismatch: float = 50e-9
    minimum_on_time: float = 500e-9
    minimum_off_time: float = 500e-9
    ambient_temperature: float = 25.0
    theta_ja: float = 40.0
    theta_jc: float | None = None  # Datasheet 0.50 K/W; set with theta_cs/sa.
    theta_cs: float | None = None  # Datasheet 0.24 K/W with greased mount.
    theta_sa: float | None = None
    junction_temperature_max: float = 175.0
    driver_other_loss: float = 0.0  # Additional loss beyond Qg and Iq.
    core_k: float | None = None  # SI Steinmetz coefficients; all five required.
    core_alpha: float | None = None
    core_beta: float | None = None
    core_delta_b: float | None = None
    core_volume: float | None = None


UNITS = {
    'vin':'V', 'vout':'V', 'pout':'W', 'supply_current_limit':'A', 'fs':'Hz',
    'inductance':'H', 'cin':'F', 'cout':'F', 'load_resistance':'ohm',
    'vin_min':'V', 'vin_max':'V', 'transition_window':'V',
    'allowed_input_ripple':'Vpp', 'allowed_output_ripple':'Vpp',
    'inductor_dcr':'ohm', 'inductor_ac_resistance':'ohm', 'cin_esr':'ohm', 'cout_esr':'ohm', 'rds_on_25':'ohm',
    'coss':'F', 'eoss':'J', 'qg':'C', 'qgd':'C', 'vdrive':'V', 'vplateau':'V',
    'driver_source_resistance':'ohm', 'driver_sink_resistance':'ohm',
    'gate_internal_resistance':'ohm', 'gate_external_resistance':'ohm',
    'desired_miller_time':'s', 'driver_quiescent_current':'A',
    'gate_power_available':'W', 'gate_pulldown_resistance':'ohm', 'diode_vf':'V',
    'dead_time':'s', 'turnoff_delay':'s', 'delay_mismatch':'s',
    'minimum_on_time':'s', 'minimum_off_time':'s', 'ambient_temperature':'degC',
    'theta_ja':'K/W', 'theta_jc':'K/W', 'theta_cs':'K/W', 'theta_sa':'K/W',
    'junction_temperature_max':'degC', 'driver_other_loss':'W',
    'core_k':'SI coefficient', 'core_delta_b':'T', 'core_volume':'m^3',
}


def validate_constants(c):
    positive = set('vin vout pout supply_current_limit fs inductance cin cout load_resistance vin_min vin_max target_ripple_fraction allowed_input_ripple allowed_output_ripple rds_hot_factor qg qgd vdrive desired_miller_time gate_power_available gate_pulldown_resistance minimum_on_time minimum_off_time theta_ja core_k core_alpha core_beta core_delta_b core_volume'.split())
    signed = {'ambient_temperature', 'junction_temperature_max'}
    for f in fields(c):
        v = getattr(c, f.name)
        if v is None:
            continue
        if not math.isfinite(v):
            raise ValueError(f'{f.name} must be finite')
        if f.name in positive and v <= 0:
            raise ValueError(f'{f.name} must be positive')
        if f.name not in positive | signed and v < 0:
            raise ValueError(f'{f.name} cannot be negative')
    if c.vin_min >= c.vin_max:
        raise ValueError('vin_min must be less than vin_max')
    if not 0 < c.transition_duty < 1 or not 0 <= c.phase_shift < 1:
        raise ValueError('transition_duty in (0,1), phase_shift in [0,1) required')
    if not 0 < c.target_ripple_fraction < 2 or c.saturation_margin < 1:
        raise ValueError('ripple fraction in (0,2), saturation margin >=1 required')
    if not 0 < c.vplateau < c.vdrive:
        raise ValueError('Miller plateau must be above zero and below vdrive')
    for driver_r in (c.driver_source_resistance, c.driver_sink_resistance):
        if driver_r+c.gate_internal_resistance+c.gate_external_resistance <= 0:
            raise ValueError('total gate resistance must be positive')
    for group in ((c.theta_jc,c.theta_cs,c.theta_sa),
                  (c.core_k,c.core_alpha,c.core_beta,c.core_delta_b,c.core_volume)):
        if any(v is not None for v in group) and not all(v is not None for v in group):
            raise ValueError('supply all thermal path parameters or none; all five core parameters or none')


# Output a list of input variables and prompt for constants in a comma-separated list.
def prompt_constants():
    defaults = Constants()
    names = [f.name for f in fields(defaults)]
    print('Enter SI values in this order; blank CSV fields retain defaults.')
    print('Component/driver/thermal defaults are illustrative. Use scientific notation.')
    for i,name in enumerate(names,1):
        print(f'{i:2}. {name} [{UNITS.get(name,"dimensionless")}] = {getattr(defaults,name)}')
    print('Example: 30,24,30,5,50000,220e-6,100e-6,100e-6')
    while True:
        try:
            raw = input('Constants (CSV; Enter for defaults): ').strip()
            tokens = raw.split(',') if raw else []
            if len(tokens) > len(names):
                raise ValueError(f'at most {len(names)} values accepted')
            c = replace(defaults, **{n:float(v) for n,v in zip(names,tokens) if v.strip()})
            validate_constants(c)
            if c.load_resistance is None:
                raw_r = input(f'Load [ohm], Enter for Vout^2/Pout ({c.vout**2/c.pout:g} ohm): ')
                if raw_r.strip():
                    c = replace(c,load_resistance=float(raw_r))
            validate_constants(c)
            return c
        except ValueError as exc:
            print(f'Invalid input: {exc}. Try again.')


# Add a load resistance; ask for it or use a reasonable default.
def calculate_load(c):
    """Page 10: R=Vout^2/Pout; explicit R takes precedence over requested power."""
    r = c.load_resistance if c.load_resistance is not None else c.vout**2/c.pout
    return {'R_load [ohm]':r, 'Iout [A]':c.vout/r, 'Pout [W]':c.vout**2/r}


def calculate_mode(vin,vout,window=0.5,transition_duty=0.7):
    """Pages 1,2,11: DA Vin = DB Vout; DB is output HIGH-SIDE duty."""
    if vin <= 0 or vout <= 0 or window < 0:
        raise ValueError('positive voltages and nonnegative transition window required')
    if vin > vout+window:
        return 'buck',vout/vin,1.0
    if vin < vout-window:
        return 'boost',1.0,vin/vout
    da,db = transition_duty*vout/vin,transition_duty
    if not 0 < da < 1 or not 0 < db < 1:
        raise ValueError('invalid transition duties: reduce transition_duty or window')
    return 'transition',da,db


# Calculate boost and buck mode ranges.
def calculate_mode_ranges(c):
    return {'buck Vin above [V]':c.vout+c.transition_window,
            'boost Vin below [V]':max(0,c.vout-c.transition_window),
            'transition Vin lower [V]':max(0,c.vout-c.transition_window),
            'transition Vin upper [V]':c.vout+c.transition_window,
            'sweep Vin min [V]':c.vin_min,'sweep Vin max [V]':c.vin_max}


def switching_intervals(da,db,phase):
    """Leading-edge PWM, output bridge shifted by phase switching periods."""
    if not 0 <= da <= 1 or not 0 < db <= 1 or not 0 <= phase < 1:
        raise ValueError('invalid duties or PWM phase')
    edges = {0.0,1.0}
    if 0 < da < 1:
        edges.add(da)
    if db < 1:
        edges.update((phase,(phase+db)%1))
    edges = sorted(edges)
    return [(a,b,float((a+b)/2 < da),float(((a+b)/2-phase)%1 < db))
            for a,b in zip(edges,edges[1:]) if b>a]


# Calculate inductor ripple.
# Calculate inductor current and inductor voltage.
# Calculate peak inductor current and required inductor saturation current.
# Calculate average inductor current and minimum current to stay in CCM.
def calculate_inductor(c,iout,da,db):
    """Pages 3-4. Boost ripple corrected to Vin*(1-DB)/(L*fs).

    Integrate VL dt/L across PWM states to also support phase-dependent
    transition ripple. Each returned segment contains dt, sA, sB, Istart, Iend.
    """
    segments,relative_i,integral = [],0.0,0.0
    for a,b,sa,sb in switching_intervals(da,db,c.phase_shift):
        dt = (b-a)/c.fs
        end_i = relative_i+(sa*c.vin-sb*c.vout)*dt/c.inductance
        integral += dt*(relative_i+end_i)/2
        segments.append((dt,sa,sb,relative_i,end_i))
        relative_i = end_i
    if abs(relative_i) > 1e-8:
        raise ValueError('inductor volt-second balance failed')
    average = iout/db
    offset = average-integral*c.fs
    segments = [(dt,sa,sb,x+offset,y+offset) for dt,sa,sb,x,y in segments]
    samples = [i for dt,sa,sb,x,y in segments for i in (x,y)]
    minimum,peak = min(samples),max(samples)
    ripple = peak-minimum
    rms2 = c.fs*sum(dt*(x*x+x*y+y*y)/3 for dt,sa,sb,x,y in segments)
    core = None if c.core_k is None else c.core_k*c.fs**c.core_alpha*c.core_delta_b**c.core_beta*c.core_volume
    # DC current sees DCR; ripple (mostly at fs) sees the measured Rs at fs.
    ac_rms2 = max(rms2-average**2,0.0)
    rac = c.inductor_dcr if c.inductor_ac_resistance is None else c.inductor_ac_resistance
    dc_loss,ac_loss = average**2*c.inductor_dcr,ac_rms2*rac
    return {'switching period [s]':1/c.fs,
            'IL average [A]':average,'Iin ideal [A]':da*average,
            'IL ripple [App]':ripple,'IL peak [A]':peak,'IL min [A]':minimum,
            'IL RMS [A]':math.sqrt(rms2),'CCM':minimum>0,
            'minimum IL average for CCM [A]':average-minimum,
            'minimum output current for CCM [A]':db*(average-minimum),
            'required Isat [A]':c.saturation_margin*peak,
            'L for target ripple [H]':c.inductance*ripple/(c.target_ripple_fraction*average),
            'target ripple [App]':c.target_ripple_fraction*average,
            'inductor peak energy [J]':0.5*c.inductance*peak**2,
            'inductor DC copper loss [W]':dc_loss,'inductor AC ripple loss [W]':ac_loss,
            'inductor copper loss [W]':dc_loss+ac_loss,
            'inductor core loss [W]':core,'VL average [V]':da*c.vin-db*c.vout,
            'VL min [V]':min(sa*c.vin-sb*c.vout for _,sa,sb,_,_ in segments),
            'VL max [V]':max(sa*c.vin-sb*c.vout for _,sa,sb,_,_ in segments)},segments


def capacitor_waveform(segments,bridge,fs):
    """Derive capacitor RMS and charge swing from piecewise linear bridge current.

    Remove its DC mean; the source/load is assumed constant within a PWM cycle.
    Include quadratic charge extrema at zero capacitor current.
    """
    mean = fs*sum(dt*(sa if bridge=='A' else sb)*(x+y)/2 for dt,sa,sb,x,y in segments)
    charge,charges,currents,rms2 = 0.0,[0.0],[],0.0
    for dt,sa,sb,x,y in segments:
        s = sa if bridge=='A' else sb
        start,end = s*x-mean,s*y-mean
        currents.extend((start,end))
        rms2 += fs*dt*(start*start+start*end+end*end)/3
        slope = (end-start)/dt
        if slope and 0 < -start/slope < dt:
            t = -start/slope
            charges.append(charge+start*t+0.5*slope*t*t)
        charge += dt*(start+end)/2
        charges.append(charge)
    return math.sqrt(rms2),max(charges)-min(charges),max(currents)-min(currents)


# Calculate output capacitance for buck and boost modes and capacitor current.
# Calculate output voltage ripple and input voltage ripple.
# Calculate input capacitance and capacitor current.
# Calculate input voltage ripple.
def calculate_capacitors(c,mode,iout,da,db,ind,segments):
    """Pages 4-5 first-order ripple/ESR estimates; reserve ESR ripple budget.

    Transition and boost-input formulas are derived from selected PWM states.
    Pulsed buck-input/boost-output formulas neglect IL ripple, as in the notes.
    """
    delta = ind['IL ripple [App]']
    ir,iq,ipp = capacitor_waveform(segments,'A',c.fs)
    orms,oq,opp = capacitor_waveform(segments,'B',c.fs)
    if mode=='buck':
        ir,iq,ipp = iout*math.sqrt(da*(1-da)),iout*da*(1-da)/c.fs,ind['IL peak [A]']
        orms,oq,opp = delta/(2*math.sqrt(3)),delta/(8*c.fs),delta
    elif mode=='boost':
        orms,oq,opp = iout*math.sqrt((1-db)/db),iout*(1-db)/c.fs,ind['IL peak [A]']
        ir,iq,ipp = delta/(2*math.sqrt(3)),delta/(8*c.fs),delta
    ie,oe = ipp*c.cin_esr,opp*c.cout_esr
    return {'Cin minimum [F]':iq/(c.allowed_input_ripple-ie) if c.allowed_input_ripple>ie else math.inf,
            'Cout minimum [F]':oq/(c.allowed_output_ripple-oe) if c.allowed_output_ripple>oe else math.inf,
            'Cin RMS current [A]':ir,'Cout RMS current [A]':orms,
            'input capacitive ripple [Vpp]':iq/c.cin,'output capacitive ripple [Vpp]':oq/c.cout,
            'input ESR ripple estimate [Vpp]':ie,'output ESR ripple estimate [Vpp]':oe,
            'input total ripple estimate [Vpp]':iq/c.cin+ie,
            'output total ripple estimate [Vpp]':oq/c.cout+oe,
            'Cin ESR loss [W]':ir**2*c.cin_esr,'Cout ESR loss [W]':orms**2*c.cout_esr}


# Calculate gate-drive current, loss, and power.
# Calculate peak gate current during the Miller plateau, Miller transition time,
# and gate resistor values.
# Calculate pull-down resistor value and current.
def calculate_gate_drive(c,da,db):
    """Pages 6-8. Only actively switching FETs dissipate periodic Qg energy."""
    switched = 2*int(0<da<1)+2*int(0<db<1)
    source_r = c.driver_source_resistance+c.gate_external_resistance+c.gate_internal_resistance
    sink_r = c.driver_sink_resistance+c.gate_external_resistance+c.gate_internal_resistance
    source_i,sink_i = (c.vdrive-c.vplateau)/source_r,c.vplateau/sink_r
    required_i = c.qgd/c.desired_miller_time
    total_r = (c.vdrive-c.vplateau)/required_i
    # Sum of four on-time fractions is two; Vgs^2/R corrects page 8 typo.
    pulldown = 2*c.vdrive**2/c.gate_pulldown_resistance
    return {'switching MOSFET count':switched,
            'average gate current per switching FET [A]':c.qg*c.fs,
            'gate power per switching FET [W]':c.qg*c.vdrive*c.fs,
            'total dynamic gate current [A]':switched*c.qg*c.fs,
            'gate dynamic power [W]':switched*c.qg*c.vdrive*c.fs,
            'driver supply current incl Iq [A]':switched*c.qg*c.fs+2*c.driver_quiescent_current+pulldown/c.vdrive,
            'driver quiescent loss [W]':2*c.driver_quiescent_current*c.vdrive,
            'gate charge frequency limit [Hz]':c.gate_power_available/(c.qg*c.vdrive) if switched else math.inf,
            'Miller source current [A]':source_i,'Miller sink current [A]':sink_i,
            'Miller rise time [s]':c.qgd/source_i,'Miller fall time [s]':c.qgd/sink_i,
            'gate resistance total for target rise [ohm]':total_r,
            'external gate resistance for target rise [ohm]':total_r-c.driver_source_resistance-c.gate_internal_resistance,
            'pulldown resistance [ohm]':c.gate_pulldown_resistance,
            'pulldown on current per FET [A]':c.vdrive/c.gate_pulldown_resistance,
            'pulldown on power per FET [W]':c.vdrive**2/c.gate_pulldown_resistance,
            'pulldown total average loss [W]':pulldown}


# Calculate the maximum switching frequency.
# Calculate dead time.
# Calculate minimum pulse width and maximum and minimum practical duty cycles.
def calculate_timing(c,gate,da,db):
    """Page 8 pulse limits; conservatively add dead time to useful pulse times."""
    required_dead = c.turnoff_delay+gate['Miller fall time [s]']+c.delay_mismatch
    on_min = max(c.minimum_on_time,gate['Miller rise time [s]'])+c.dead_time
    off_min = max(c.minimum_off_time,c.turnoff_delay+gate['Miller fall time [s]'])+c.dead_time
    pulse_limit = min((min(d/on_min,(1-d)/off_min) for d in (da,db) if 0<d<1),default=math.inf)
    result = {'required dead time lower bound [s]':required_dead,'configured dead time [s]':c.dead_time,
              'dead time meets lower bound':c.dead_time>required_dead,
              'dead time fraction per switched leg':2*c.dead_time*c.fs,
              'minimum effective on pulse [s]':on_min,'minimum effective off pulse [s]':off_min,
              'practical duty min':c.fs*on_min,'practical duty max':1-c.fs*off_min,
              'pulse frequency limit at operating duties [Hz]':pulse_limit,
              'maximum estimated switching frequency [Hz]':min(gate['gate charge frequency limit [Hz]'],pulse_limit,1/(2*c.dead_time) if c.dead_time else math.inf)}
    for name,d in (('A',da),('B',db)):
        result[f'{name} high-side on time [s]'] = d/c.fs
        result[f'{name} high-side off time [s]'] = (1-d)/c.fs
        result[f'{name} duty practical'] = d in (0,1) or c.fs*on_min<=d<=1-c.fs*off_min
    return result


# Calculate the Vds rating needed for each transistor.
# Calculate current and losses for each transistor.
# Calculate MOSFET loss and body-diode loss.
def calculate_mosfets(c,ind,gate,da,db):
    """Pages 5-8: first-order losses at mean IL; no reverse-recovery model.

    Diode loss 2*td*fs*Vf*IL is PER LEG, divided between its two FETs.
    Gate supply power is counted separately, once, in the converter budget.
    """
    devices = {}
    irms2,il = ind['IL RMS [A]']**2,ind['IL average [A]']
    for leg,duty,voltage in (('A',da,c.vin),('B',db,c.vout)):
        switching = 0<duty<1
        diode_leg = c.diode_vf*il*2*c.dead_time*c.fs if switching else 0.0
        for side,fraction in (('HS',duty),('LS',1-duty)):
            cond = irms2*c.rds_on_25*c.rds_hot_factor*fraction
            sw = 0.5*voltage*il*(gate['Miller rise time [s]']+gate['Miller fall time [s]'])*c.fs if switching else 0.0
            coss = (c.eoss if c.eoss is not None else 0.5*c.coss*voltage**2)*c.fs if switching else 0.0
            diode = diode_leg/2
            devices[f'{leg}_{side}'] = {
                'duty':fraction,'RMS current [A]':math.sqrt(irms2*fraction),
                'required peak current above [A]':ind['IL peak [A]'],
                'blocking voltage [V]':voltage,
                'suggested Vds rating at 1.5x [V]':1.5*max(voltage,c.vin_max if leg=='A' else c.vout),
                'conduction loss [W]':cond,'switching overlap loss [W]':sw,
                'Coss loss [W]':coss,'body diode loss [W]':diode,
                'total FET loss [W]':cond+sw+coss+diode}
    return devices


# Calculate junction temperature.
def calculate_junction_temperatures(c,devices):
    """Page 11 thetaJA, or thetaJC+thetaCS with a shared heatsink thetaSA."""
    total = sum(d['total FET loss [W]'] for d in devices.values())
    result = {}
    for name,d in devices.items():
        p = d['total FET loss [W]']
        tj = c.ambient_temperature+p*c.theta_ja if c.theta_jc is None else c.ambient_temperature+total*c.theta_sa+p*(c.theta_jc+c.theta_cs)
        result[f'{name} junction estimate [degC]'] = tj
        result[f'{name} below maximum junction temperature'] = tj<c.junction_temperature_max
    return result


# Calculate converter efficiency.
def calculate_efficiency(c,load,ind,caps,gate,devices):
    """Page 11 budget; missing core loss means a partial efficiency estimate."""
    core = ind['inductor core loss [W]']
    loss = (sum(d['total FET loss [W]'] for d in devices.values())
            +ind['inductor copper loss [W]']+(core if core is not None else 0)
            +caps['Cin ESR loss [W]']+caps['Cout ESR loss [W]']
            +gate['gate dynamic power [W]']+gate['driver quiescent loss [W]']
            +gate['pulldown total average loss [W]']+c.driver_other_loss)
    pin = load['Pout [W]']+loss
    return {'core loss included':core is not None,'modeled total loss [W]':loss,
            'estimated Pin [W]':pin,'estimated Iin including losses [A]':pin/c.vin,
            'estimated efficiency [%]':100*load['Pout [W]']/pin,
            'estimated Iin within supply limit':pin/c.vin<=c.supply_current_limit}


# Calculate losses for converter components.
def calculate_all(c):
    validate_constants(c)
    load = calculate_load(c)
    mode,da,db = calculate_mode(c.vin,c.vout,c.transition_window,c.transition_duty)
    ind,segments = calculate_inductor(c,load['Iout [A]'],da,db)
    caps = calculate_capacitors(c,mode,load['Iout [A]'],da,db,ind,segments)
    gate = calculate_gate_drive(c,da,db)
    devices = calculate_mosfets(c,ind,gate,da,db)
    ideal_sim = switching_summary(c,c.vin,da,db)
    sim = {f'ideal-duty lossless {k}':v for k,v in ideal_sim.items() if 'ripple' in k or 'average' in k}
    try:
        _,rda,rdb = regulated_duties(c,c.vin)
        sim.update({f'regulated {k}':v for k,v in switching_summary(c,c.vin,rda,rdb,series_resistance(c)).items()})
    except ValueError as exc:
        sim['regulated operating point'] = f'unreachable: {exc}'
    return {'Operating point':{'mode':mode,'DA (input HS)':da,'DB (output HS)':db,'boost low-side duty':1-db,**load},
            'Mode ranges':calculate_mode_ranges(c),'Inductor':ind,'Capacitors':caps,'Gate drive':gate,
            'Timing':calculate_timing(c,gate,da,db),
            **{f'MOSFET {name}':d for name,d in devices.items()},
            'Junction temperatures':calculate_junction_temperatures(c,devices),
            'Loss budget':calculate_efficiency(c,load,ind,caps,gate,devices),
            'Switching simulation':sim}


def series_resistance(c):
    """Coil DCR plus one conducting FET per leg (dead time neglected)."""
    return c.inductor_dcr+2*c.rds_on_25*c.rds_hot_factor


def regulated_duties(c,vin):
    """Duties that hold Vout at the load despite the series-resistance drop.

    This is the operating point a voltage loop would settle at. Buck and
    transition raise DA; boost solves Vout R DB^2 - Vin R DB + Rs Vout = 0.
    """
    mode,da,db = calculate_mode(vin,c.vout,c.transition_window,c.transition_duty)
    r,rs = calculate_load(c)['R_load [ohm]'],series_resistance(c)
    if mode=='boost':
        disc = (vin*r)**2-4*c.vout**2*r*rs
        if disc<0:
            raise ValueError(f'Vin={vin:g} V cannot reach Vout through {rs:g} ohm series resistance')
        da,db = 1.0,(vin*r+math.sqrt(disc))/(2*c.vout*r)
    else:
        da = (db*c.vout+rs*c.vout/(db*r))/vin
    if not 0<da<=1 or not 0<db<=1:
        raise ValueError(f'{mode} at Vin={vin:g} V needs DA={da:.3f}, DB={db:.3f}: '
                         f'the {rs*c.vout/(db*r):.3g} V series drop exceeds the transition window')
    return mode,da,db


def state_space_derivatives(state,vin,da,db,inductance,cout,resistance,series_r=0.0):
    """Page 9 generalized averaged CCM equations, plus series loss resistance."""
    il,vout = state
    return np.array([(da*vin-db*vout-series_r*il)/inductance,(db*il-vout/resistance)/cout])


def buck_state_space(state,vin,duty,inductance,cout,resistance):
    return state_space_derivatives(state,vin,duty,1,inductance,cout,resistance)


def boost_state_space(state,vin,duty,inductance,cout,resistance):
    """duty is the boost LOW-SIDE duty, as on page 2."""
    return state_space_derivatives(state,vin,1,1-duty,inductance,cout,resistance)


def transition_state_space(state,vin,da,db,inductance,cout,resistance):
    return state_space_derivatives(state,vin,da,db,inductance,cout,resistance)


# Use buck, boost, and transition state-space equations to simulate the topology
# across duty cycle and/or input/output voltage.
def simulate_state_space(c,vin,da,db,duration=None,initial_state=None,step=None,series_r=0.0):
    """Bounded RK4 averaged open-loop CCM disturbance response, not startup/DCM.

    Default duration is ten decay time constants. Step is constrained by
    eigenvalue magnitude and switching period; allow halving for convergence.
    """
    validate_constants(c)
    if not 0<da<=1 or not 0<db<=1 or vin<=0:
        raise ValueError('simulation requires positive Vin and duties in (0,1]')
    r = calculate_load(c)['R_load [ohm]']
    eq_v = da*vin/(db+series_r/(db*r))
    equilibrium = np.array([eq_v/(db*r),eq_v])
    eigenvalues = np.linalg.eigvals([[-series_r/c.inductance,-db/c.inductance],[db/c.cout,-1/(r*c.cout)]])
    max_step = min(1/(20*c.fs),0.05/max(abs(eigenvalues)))
    dt = max_step if step is None else step
    if not math.isfinite(dt) or not 0<dt<=max_step:
        raise ValueError(f'step must be positive and <= {max_step:g} s')
    duration = 10/min(-eigenvalues.real) if duration is None else duration
    if not math.isfinite(duration) or duration<=0:
        raise ValueError('duration must be finite and positive')
    count = math.ceil(duration/dt)+1
    if count>250000:
        raise ValueError('simulation exceeds 250000 samples; shorten --duration')
    times = np.linspace(0,duration,count)
    states = np.empty((count,2))
    states[0] = equilibrium*np.array([1,0.99]) if initial_state is None else initial_state
    if not np.all(np.isfinite(states[0])):
        raise ValueError('initial state must be finite')
    def derivative(x):
        return state_space_derivatives(x,vin,da,db,c.inductance,c.cout,r,series_r)
    for n in range(count-1):
        h,x = times[n+1]-times[n],states[n]
        k1 = derivative(x)
        k2 = derivative(x+h*k1/2)
        k3 = derivative(x+h*k2/2)
        k4 = derivative(x+h*k3)
        states[n+1] = x+h*(k1+2*k2+2*k3+k4)/6
    if not np.all(np.isfinite(states)):
        raise ValueError('non-finite simulation result')
    return times,states,equilibrium


def affine_flow(a,b,h):
    """Exact solution map of x' = A x + b over h: x(h) = E x(0) + g."""
    n = len(b)
    m = np.zeros((n+1,n+1))
    m[:n,:n],m[:n,n] = a*h,b*h
    squarings = max(0,math.ceil(math.log2(max(np.abs(m).sum(axis=1).max(),1e-300)))+1)
    m /= 2**squarings
    result,term = np.eye(n+1),np.eye(n+1)
    for k in range(1,16):
        term = term@m/k
        result += term
    for _ in range(squarings):
        result = result@result
    return result[:n,:n],result[:n,n]


def simulate_switching(c,vin,da,db,series_r=0.0,samples=2000):
    """Exact periodic steady state of the switched circuit, iL and Cout voltage.

    Synchronous switches allow negative iL, so there is no DCM. Vin is stiff,
    dead time is neglected, and Cout ESR appears in the output voltage. Solves
    x(T) = x(0) for the per-period affine map rather than integrating a startup.
    """
    validate_constants(c)
    r,esr = calculate_load(c)['R_load [ohm]'],c.cout_esr
    k = r/(r+esr)
    def system(sa,sb):
        a = np.array([[-(series_r+sb*k*esr)/c.inductance,-sb*k/c.inductance],
                      [sb*k/c.cout,-k/(r*c.cout)]])
        return a,np.array([sa*vin/c.inductance,0.0])
    intervals = switching_intervals(da,db,c.phase_shift)
    phi,gamma = np.eye(2),np.zeros(2)
    for a0,b0,sa,sb in intervals:
        e,g = affine_flow(*system(sa,sb),(b0-a0)/c.fs)
        phi,gamma = e@phi,e@gamma+g
    x = np.linalg.solve(np.eye(2)-phi,gamma)
    times,states,switches = [0.0],[x],[intervals[0][2:]]
    for a0,b0,sa,sb in intervals:
        n = max(2,round(samples*(b0-a0)))
        e,g = affine_flow(*system(sa,sb),(b0-a0)/(n*c.fs))
        for i in range(1,n+1):
            x = e@x+g
            times.append((a0+(b0-a0)*i/n)/c.fs)
            states.append(x)
            switches.append((sa,sb))
    states,switches = np.array(states),np.array(switches)
    vout = k*(states[:,1]+esr*switches[:,1]*states[:,0])
    if abs(states[-1]-states[0]).max()>1e-6*max(1,abs(states[0]).max()):
        raise ValueError('switched steady state is not periodic')
    return np.array(times),states[:,0],vout,switches


def switching_summary(c,vin,da,db,series_r=0.0):
    t,il,vout,_ = simulate_switching(c,vin,da,db,series_r)
    dt = np.diff(t)
    mean = lambda y: float(np.sum(dt*(y[1:]+y[:-1])/2)*c.fs)
    return {'Vin [V]':vin,'DA':da,'DB':db,'series resistance [ohm]':series_r,
            'IL average [A]':mean(il),'IL ripple [App]':float(il.max()-il.min()),
            'IL peak [A]':float(il.max()),'IL min [A]':float(il.min()),
            'Vout average [V]':mean(vout),'Vout ripple [Vpp]':float(vout.max()-vout.min())}


def plot_switching(c,output_path,cases,show=True):
    """Two switching periods of steady-state iL and Vout for each case."""
    import matplotlib.pyplot as plt
    fig,axes = plt.subplots(2,len(cases),figsize=(13,6.5),layout='constrained',squeeze=False)
    for column,(mode,vin,da,db,rs) in enumerate(cases):
        t,il,vout,_ = simulate_switching(c,vin,da,db,rs)
        t2 = np.concatenate((t,t[1:]+1/c.fs))*1e6
        for row,(y,label) in enumerate(((il,'Inductor current [A]'),(vout,'Output voltage [V]'))):
            ax = axes[row,column]
            ax.plot(t2,np.concatenate((y,y[1:])))
            ax.set(xlabel='Time [µs]',ylabel=label)
            ax.ticklabel_format(axis='y',useOffset=False)
            ax.grid(alpha=0.3)
        axes[0,column].set_title(f'{mode}: Vin={vin:g} V, DA={da:.3f}, DB={db:.3f}\n'
                                 f'ΔiL={il.max()-il.min():.3g} App, ΔVout={1e3*(vout.max()-vout.min()):.3g} mVpp')
    fig.suptitle(f'Switched steady state, two periods at {c.fs/1e3:g} kHz '
                 f'(L={c.inductance*1e6:.0f} µH, Cout={c.cout*1e6:.0f} µF, ESR={c.cout_esr*1e3:g} mΩ)')
    fig.savefig(output_path,dpi=160)
    if not show:
        plt.close(fig)
    return output_path


def plot_state_space(c,output_path,show=True,duration=None):
    """Pyplot mode responses and a Vin/high-side-duty steady-state sweep."""
    import matplotlib.pyplot as plt
    rs = series_resistance(c)
    cases = [('Buck',max(c.vin,1.25*c.vout)),('Boost',0.75*c.vout),('Transition',c.vout)]
    cases = [(mode,vin,*regulated_duties(c,vin)[1:],rs) for mode,vin in cases]
    fig,axes = plt.subplots(2,3,figsize=(13,7),layout='constrained')
    for column,(mode,vin,da,db,_) in enumerate(cases):
        ideal_da,ideal_db = calculate_mode(vin,c.vout,c.transition_window,c.transition_duty)[1:]
        ideal_t,ideal,_ = simulate_state_space(c,vin,ideal_da,ideal_db,duration)
        times,states,eq = simulate_state_space(c,vin,da,db,ideal_t[-1],series_r=rs)
        for row,(label,unit) in enumerate((('Inductor current','A'),('Output voltage','V'))):
            ax = axes[row,column]
            ax.plot(ideal_t*1e3,ideal[:,row],color='gray',alpha=0.4,lw=0.8,label='Lossless, ideal duties')
            ax.plot(times*1e3,states[:,row],label=f'With {rs:.3g} Ω series R')
            ax.axhline(eq[row],color='black',linestyle='--',label='Steady state')
            ax.set(xlabel='Time [ms]',ylabel=f'{label} [{unit}]')
            ax.grid(alpha=0.3)
            if row==0:
                ax.set_title(f'{mode}: Vin={vin:g} V\nDA={da:.3f}, DB={db:.3f}')
        axes[1,column].legend()
    fig.suptitle('Averaged open-loop CCM: 1% output-voltage disturbance (LC resonance, not switching ripple)\n'
                 'diL/dt=(DA Vin-DB Vout-Rs iL)/L; dVout/dt=(DB iL-Vout/R)/Cout; Rs = DCR + 2 Rds,hot')
    output_path = Path(output_path).resolve()
    if not output_path.suffix:
        output_path = output_path.with_suffix('.png')
    output_path.parent.mkdir(parents=True,exist_ok=True)
    fig.savefig(output_path,dpi=160)
    sweep_fig,sweep_axes = plt.subplots(2,1,figsize=(9,6),sharex=True,layout='constrained')
    inputs = np.linspace(c.vin_min,c.vin_max,300)
    duties = np.array([calculate_mode(v,c.vout,c.transition_window,c.transition_duty)[1:] for v in inputs])
    r = calculate_load(c)['R_load [ohm]']
    sweep_axes[0].plot(inputs,duties[:,0],label='DA input HS')
    sweep_axes[0].plot(inputs,duties[:,1],label='DB output HS')
    sweep_axes[0].set(ylabel='High-side duty',ylim=(0,1.05))
    sweep_axes[1].plot(inputs,c.vout/(duties[:,1]*r),label='IL steady state [A]')
    sweep_axes[1].set(xlabel='Input voltage [V]',ylabel='Inductor current [A]')
    for ax in sweep_axes:
        ax.axvspan(max(0,c.vout-c.transition_window),c.vout+c.transition_window,color='orange',alpha=0.2)
        ax.set_xlim(c.vin_min,c.vin_max)
        ax.grid(alpha=0.3)
        ax.legend()
    sweep_fig.suptitle('Steady-state duties/current vs. Vin (orange = transition window)')
    sweep_path = output_path.with_name(output_path.stem+'-sweep'+output_path.suffix)
    sweep_fig.savefig(sweep_path,dpi=160)
    switching_path = plot_switching(c,output_path.with_name(output_path.stem+'-switching'+output_path.suffix),cases,show)
    if show:
        plt.show()
    else:
        plt.close(fig)
        plt.close(sweep_fig)
    return output_path,sweep_path,switching_path


def print_results(c,results):
    print('\nAnalytical estimates; gate-driver and thermal-path defaults are illustrative.')
    print('Losses omit reverse recovery, wiring and unmodeled effects.')
    for section,values in results.items():
        print(f'\n{section}')
        for name,value in values.items():
            rendered = 'unavailable (supply core parameters)' if value is None else f'{value:.7g}' if isinstance(value,float) else str(value)
            print(f'  {name}: {rendered}')
    ind,caps,timing,gate = (results[s] for s in ('Inductor','Capacitors','Timing','Gate drive'))
    warnings = []
    if not ind['CCM']:
        warnings.append('IL reaches zero: CCM design/state equations are outside their domain.')
    if ind['IL ripple [App]']>ind['target ripple [App]']:
        warnings.append('Inductor ripple exceeds target; increase L.')
    for label,actual,minimum in (('Cin',c.cin,caps['Cin minimum [F]']),('Cout',c.cout,caps['Cout minimum [F]'])):
        if math.isinf(minimum):
            warnings.append(f'{label} ESR exhausts ripple budget; capacitance alone cannot fix it.')
        elif actual<minimum:
            warnings.append(f'Selected {label} does not meet ripple budget.')
    if not timing['dead time meets lower bound']:
        warnings.append('Configured dead time is below estimated turn-off/mismatch requirement.')
    if not timing['A duty practical'] or not timing['B duty practical']:
        warnings.append('An operating duty violates pulse-width limits.')
    if gate['external gate resistance for target rise [ohm]']<0:
        warnings.append('Target Miller time requires lower driver/internal resistance.')
    if c.fs>timing['maximum estimated switching frequency [Hz]']:
        warnings.append('Frequency exceeds estimated gate/pulse/dead-time limit.')
    if any(v is False for k,v in results['Junction temperatures'].items() if 'below maximum' in k):
        warnings.append('A modeled junction temperature exceeds its maximum.')
    if not results['Loss budget']['estimated Iin within supply limit']:
        warnings.append('Estimated input current exceeds supply limit.')
    if 'regulated operating point' in results['Switching simulation']:
        warnings.append('Series-resistance drop makes this Vin unreachable in the selected mode; widen transition_window.')
    print('\nChecks')
    for warning in warnings:
        print(f'  WARNING: {warning}')
    if not warnings:
        print('  No analytical-limit violations detected.')
    if not results['Loss budget']['core loss included']:
        print('  Efficiency is a partial estimate: core loss is unavailable.')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--defaults',action='store_true',help='use illustrative constants without prompts')
    parser.add_argument('--set',action='append',default=[],metavar='NAME=VALUE',help='override an SI constant; repeatable')
    parser.add_argument('--no-show',action='store_true',help='save figures without opening windows')
    parser.add_argument('--no-plot',action='store_true',help='print calculations only')
    parser.add_argument('--plot-path',type=Path,default=Path(__file__).with_name('state-space.png'))
    parser.add_argument('--duration',type=float,help='response duration in seconds')
    args = parser.parse_args(argv)
    try:
        c = Constants() if args.defaults else prompt_constants()
        names = {f.name for f in fields(c)}
        overrides = {}
        for token in args.set:
            name,value = token.split('=',1)
            if name not in names:
                raise ValueError(f'unknown constant: {name}')
            overrides[name] = float(value)
        c = replace(c,**overrides)
        results = calculate_all(c)
        print_results(c,results)
        if not args.no_plot:
            if args.no_show:
                import matplotlib
                matplotlib.use('Agg')
            paths = plot_state_space(c,args.plot_path,not args.no_show,args.duration)
            for path in paths:
                print(f'Saved plot: {path}')
    except (ValueError,OverflowError,EOFError) as exc:
        parser.error(str(exc))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
