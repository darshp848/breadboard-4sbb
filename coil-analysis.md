# Coil measurement analysis — 2026-10-07

Transcribed readings: 19. Approximate wire: 24 AWG (unconfirmed).
Former: 3D-printed plastic; no magnetic core.

Reference frequency: 50000 Hz.

| Nominal test level | Ls [µH] | Rs [ohm] | Selection |
|---|---:|---:|---|
| 0.1 V | 558.6351 | 17.257160 | measured |
| 1 V | 557.5985 | 18.822360 | measured |

Mean of the two reference-frequency Ls values: 558.1168 µH (0.0005581168 H).
1 V versus 100 mV Ls difference: -0.1856%. This is not a saturation test.

Isat: not applicable: air-core coil on a plastic former. No finite magnetic saturation threshold is calculated.
Thermal current rating: undetermined. Air-core construction does not remove winding heating or insulation limits.

| Frequency [Hz] | Ls at 100 mV [µH] | Ls at 1 V [µH] |
|---:|---:|---:|
| 20 | 630.1741 | 637.4463 |
| 100 | 631.5651 | 636.0213 |
| 1000 | 616.4239 | 624.3178 |
| 10000 | 590.3119 | 594.5439 |
| 20000 | 579.2459 | 581.8004 |
| 50000 | 558.6351 | 557.5985 |
| 100000 | 529.9522 | 526.6928 |
| 500000 | 462.7266 | 457.3927 |

Maximum |VAC/IAC vs. series-model impedance| difference: 0.0039%.
This is a transcription/unit consistency check, not an independent accuracy calibration.
Measured AC RMS current range: 0.067514–9.8892 mA.

Ls and Rs are frequency-specific, small-signal equivalent series values. Do not average the entire sweep into one inductance or use high-frequency Rs as winding DCR.
The rise in Rs and change in Ls require fixture/parasitic and winding-loss investigation if accuracy at high frequency matters; their causes are not isolated by these photos.
The 1 MHz point has no 100 mV counterpart. Curves join measured points and do not establish self-resonant frequency.

Measure DC winding resistance and temperature rise under the intended current waveform/cooling to establish a thermal current limit. Identify both plastic and enamel temperature limits. No saturation remeasurement is required for this air-core coil.

Sources and instrument settings: [coil-measurement-notes.md](coil-measurement-notes.md).
