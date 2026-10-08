"""Plot photographed air-core coil Ls/Rs sweeps at 100 mV and 1 V.

python plot-coil.py                 # print analysis, save files, show pyplot
python plot-coil.py --no-show       # save figures without opening windows
python plot-coil.py --reference-frequency 1000 --no-show

The plastic former has no magnetic saturation threshold. Thermal current is
unknown unless a measured DCR and independently justified loss budget are given.
"""
import argparse
import csv
import math
from pathlib import Path
import numpy as np

DIRECTORY = Path(__file__).resolve().parent
NUMERIC_FIELDS = ('frequency_hz','test_level_v','ls_uh','rs_ohm',
                  'vac_rms_v','iac_rms_a','dc_bias_setting_v')


# Read the transcribed measurements with units explicitly recorded in the header.
def load_measurements(path):
    with Path(path).open(encoding='utf-8-sig',newline='') as stream:
        rows = list(csv.DictReader(stream))
    if not rows:
        raise ValueError('measurement CSV is empty')
    seen = set()
    for row in rows:
        for name in NUMERIC_FIELDS:
            row[name] = float(row[name])
            if not math.isfinite(row[name]):
                raise ValueError(f'{name} must be finite')
            if name != 'dc_bias_setting_v' and row[name] <= 0:
                raise ValueError(f'{name} must be positive')
        key = (row['test_level_v'],row['frequency_hz'])
        if key in seen:
            raise ValueError(f'duplicate test-level/frequency pair: {key}')
        seen.add(key)
        if row['test_level_v'] not in (0.1,1.0):
            raise ValueError('this analysis expects 100 mV and 1 V test levels')
        if row['dc_bias_setting_v'] != 0 or row['idc_monitor'] != 'OFF':
            raise ValueError('these source photos are zero-bias sweeps, not DC-bias measurements')
    if {r['test_level_v'] for r in rows} != {0.1,1.0}:
        raise ValueError('both test levels are required')
    return rows


# Calculate reactance, impedance magnitude and Q from the equivalent series model.
def calculate_impedance(row):
    xl = 2*math.pi*row['frequency_hz']*row['ls_uh']*1e-6
    magnitude = math.hypot(row['rs_ohm'],xl)
    monitor = row['vac_rms_v']/row['iac_rms_a']
    return {'ls_h':row['ls_uh']*1e-6,'xl_ohm':xl,'z_magnitude_ohm':magnitude,
            'q_series':xl/row['rs_ohm'],'monitor_z_ohm':monitor,
            'monitor_difference_percent':100*(monitor/magnitude-1),
            'iac_peak_a':math.sqrt(2)*row['iac_rms_a']}


# Calculate inductance and series resistance at the requested reference frequency.
def reference_values(rows,level,frequency):
    if not math.isfinite(frequency) or frequency<=0:
        raise ValueError('reference frequency must be positive and finite')
    points = sorted((r for r in rows if r['test_level_v']==level),key=lambda r:r['frequency_hz'])
    frequencies = [r['frequency_hz'] for r in points]
    if not frequencies[0]<=frequency<=frequencies[-1]:
        raise ValueError(f'reference frequency outside measured {level:g} V range; no extrapolation')
    for point in points:
        if point['frequency_hz']==frequency:
            return {'ls_uh':point['ls_uh'],'rs_ohm':point['rs_ohm'],'method':'measured'}
    log_f = np.log10(frequencies)
    return {'ls_uh':float(np.interp(math.log10(frequency),log_f,[p['ls_uh'] for p in points])),
            'rs_ohm':float(np.interp(math.log10(frequency),log_f,[p['rs_ohm'] for p in points])),
            'method':'interpolated in log frequency; not a measurement'}


# A plastic former does not have a magnetic saturation current; report N/A.
def calculate_coil_parameters(rows,frequency):
    refs = {level:reference_values(rows,level,frequency) for level in (0.1,1.0)}
    return {'reference_frequency_hz':frequency,'references':refs,
            'mean_ls_uh':sum(r['ls_uh'] for r in refs.values())/2,
            'ls_level_difference_percent':100*(refs[1.0]['ls_uh']/refs[0.1]['ls_uh']-1),
            'isat_a':None,'isat_status':'not applicable: air-core coil on a plastic former',
            'thermal_current_status':'undetermined from frequency sweeps and approximate wire gauge'}


# Optional conditional current budget: I = sqrt(Pallowed / Rdc), not an ampacity rating.
def calculate_dc_loss_budget(dcr_ohm,allowed_loss_w):
    if not all(math.isfinite(v) and v>0 for v in (dcr_ohm,allowed_loss_w)):
        raise ValueError('DCR and allowed DC loss must be positive and finite')
    return math.sqrt(allowed_loss_w/dcr_ohm)


# Save derived quantities while preserving each original source row.
def write_derived_csv(rows,path):
    derived = [{**row,**calculate_impedance(row)} for row in rows]
    with Path(path).open('w',encoding='utf-8',newline='') as stream:
        writer = csv.DictWriter(stream,fieldnames=list(derived[0]))
        writer.writeheader()
        writer.writerows(derived)


# Plot Ls and Rs against frequency for both AC test levels, using all measured points.
def plot_measurements(rows,path,show=True):
    import matplotlib.pyplot as plt
    fig,axes = plt.subplots(2,1,figsize=(10,8),sharex=True,layout='constrained')
    for level,label,color in ((0.1,'100 mV test level','#1464a5'),(1.0,'1 V test level','#ca6222')):
        points = sorted((r for r in rows if r['test_level_v']==level),key=lambda r:r['frequency_hz'])
        f = [r['frequency_hz'] for r in points]
        axes[0].semilogx(f,[r['ls_uh'] for r in points],'-o',label=label,color=color)
        axes[1].loglog(f,[r['rs_ohm'] for r in points],'-o',label=label,color=color)
    axes[0].set(ylabel='Equivalent series inductance Ls [µH]')
    axes[1].set(xlabel='Frequency [Hz]',ylabel='Equivalent series resistance Rs [ohm]')
    for ax in axes:
        ax.grid(which='both',alpha=0.25)
        ax.legend()
    axes[1].set_xticks([20,100,1000,10000,50000,100000,500000,1000000],
                      ['20','100','1k','10k','50k','100k','500k','1M'])
    fig.suptitle('Air-core coil on a plastic former — Keysight E4980AL Ls–Rs\n'
                 'Zero DC bias; markers are measurements; test LEVEL differs from terminal VAC')
    path = Path(path)
    fig.savefig(path,dpi=180)
    if show:
        plt.show()
    else:
        plt.close(fig)


# Report frequency-specific inductance, data checks and saturation applicability.
def build_report(rows,result,dcr=None,allowed_loss=None):
    lines = ['# Coil measurement analysis — 2026-10-07','',
             f"Transcribed readings: {len(rows)}. Approximate wire: 24 AWG (unconfirmed).",
             'Former: 3D-printed plastic; no magnetic core.','',
             f"Reference frequency: {result['reference_frequency_hz']:g} Hz.",'',
             '| Nominal test level | Ls [µH] | Rs [ohm] | Selection |',
             '|---|---:|---:|---|']
    for level in (0.1,1.0):
        r = result['references'][level]
        lines.append(f"| {level:g} V | {r['ls_uh']:.4f} | {r['rs_ohm']:.6f} | {r['method']} |")
    lines += ['',f"Mean of the two reference-frequency Ls values: {result['mean_ls_uh']:.4f} µH ({result['mean_ls_uh']*1e-6:.8g} H).",
              f"1 V versus 100 mV Ls difference: {result['ls_level_difference_percent']:+.4f}%. This is not a saturation test.",
              '',f"Isat: {result['isat_status']}. No finite magnetic saturation threshold is calculated.",
              'Thermal current rating: undetermined. Air-core construction does not remove winding heating or insulation limits.',
              '', '| Frequency [Hz] | Ls at 100 mV [µH] | Ls at 1 V [µH] |',
              '|---:|---:|---:|']
    common = sorted({r['frequency_hz'] for r in rows if r['test_level_v']==0.1}
                    & {r['frequency_hz'] for r in rows if r['test_level_v']==1})
    for f in common:
        values = [reference_values(rows,level,f)['ls_uh'] for level in (0.1,1)]
        lines.append(f'| {f:g} | {values[0]:.4f} | {values[1]:.4f} |')
    differences = [abs(calculate_impedance(r)['monitor_difference_percent']) for r in rows]
    lines += ['',f"Maximum |VAC/IAC vs. series-model impedance| difference: {max(differences):.4f}%.",
              'This is a transcription/unit consistency check, not an independent accuracy calibration.',
              f"Measured AC RMS current range: {min(r['iac_rms_a'] for r in rows)*1000:.5g}–{max(r['iac_rms_a'] for r in rows)*1000:.5g} mA.",
              '', 'Ls and Rs are frequency-specific, small-signal equivalent series values. Do not average the entire sweep into one inductance or use high-frequency Rs as winding DCR.',
              'The rise in Rs and change in Ls require fixture/parasitic and winding-loss investigation if accuracy at high frequency matters; their causes are not isolated by these photos.',
              'The 1 MHz point has no 100 mV counterpart. Curves join measured points and do not establish self-resonant frequency.',
              '', 'Measure DC winding resistance and temperature rise under the intended current waveform/cooling to establish a thermal current limit. Identify both plastic and enamel temperature limits. No saturation remeasurement is required for this air-core coil.']
    if dcr is not None:
        current = calculate_dc_loss_budget(dcr,allowed_loss)
        lines += ['',f'Conditional DC loss budget: Rdc={dcr:g} ohm, Pallowed={allowed_loss:g} W -> I={current:.6g} A.',
                  'This assumes the supplied resistance and loss allowance; it excludes AC losses and temperature feedback and is not a current rating.']
    lines += ['', 'Sources and instrument settings: [coil-measurement-notes.md](coil-measurement-notes.md).']
    return '\n'.join(lines)+'\n'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--csv',type=Path,default=DIRECTORY/'coil-measurements.csv')
    parser.add_argument('--reference-frequency',type=float,default=50000,help='reference frequency in Hz; no extrapolation')
    parser.add_argument('--output-dir',type=Path,default=DIRECTORY)
    parser.add_argument('--no-show',action='store_true')
    parser.add_argument('--dcr-ohm',type=float,help='separately measured DC winding resistance')
    parser.add_argument('--allowed-loss-w',type=float,help='independently justified DC heating allowance')
    args = parser.parse_args(argv)
    try:
        rows = load_measurements(args.csv)
        if max(abs(calculate_impedance(r)['monitor_difference_percent']) for r in rows)>0.1:
            raise ValueError('monitor/model mismatch exceeds 0.1%; check transcription before analysis')
        if (args.dcr_ohm is None)!=(args.allowed_loss_w is None):
            raise ValueError('provide both --dcr-ohm and --allowed-loss-w, or neither')
        result = calculate_coil_parameters(rows,args.reference_frequency)
        report = build_report(rows,result,args.dcr_ohm,args.allowed_loss_w)
        args.output_dir.mkdir(parents=True,exist_ok=True)
        write_derived_csv(rows,args.output_dir/'coil-derived.csv')
        (args.output_dir/'coil-analysis.md').write_text(report,encoding='utf-8')
        if args.no_show:
            import matplotlib
            matplotlib.use('Agg')
        plot_measurements(rows,args.output_dir/'coil-ls-rs-vs-frequency.png',not args.no_show)
        print(report)
        print(f"Saved figure: {(args.output_dir/'coil-ls-rs-vs-frequency.png').resolve()}")
    except (ValueError,OSError,KeyError) as exc:
        parser.error(str(exc))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
