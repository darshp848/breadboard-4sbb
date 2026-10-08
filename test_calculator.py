"""Physics and CLI regression checks; run: python -m unittest discover -s breadboard-4sbb -p 'test_*.py'."""
import importlib.util
from dataclasses import replace
from pathlib import Path
import subprocess
import sys
import unittest
import numpy as np

PATH = Path(__file__).with_name('4sbb-calculator.py')
spec = importlib.util.spec_from_file_location('calculator',PATH)
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)


class CalculatorTests(unittest.TestCase):
    def test_equilibria_and_power_balance_all_modes(self):
        for vin in (40,20,30,29.8,30.2):
            c = replace(m.Constants(),vin=vin)
            result = m.calculate_all(c)
            op,ind = result['Operating point'],result['Inductor']
            state = (ind['IL average [A]'],c.vout)
            derivative = m.state_space_derivatives(state,vin,op['DA (input HS)'],op['DB (output HS)'],c.inductance,c.cout,op['R_load [ohm]'])
            np.testing.assert_allclose(derivative,0,atol=1e-8)
            self.assertAlmostEqual(vin*ind['Iin ideal [A]'],op['Pout [W]'])

    def test_ripple_against_voltage_time_equations(self):
        for vin in (40,20):
            c = replace(m.Constants(),vin=vin)
            result = m.calculate_all(c)
            op = result['Operating point']
            expected = (vin-c.vout)*op['DA (input HS)']/(c.inductance*c.fs) if vin>c.vout else vin*(1-op['DB (output HS)'])/(c.inductance*c.fs)
            self.assertAlmostEqual(result['Inductor']['IL ripple [App]'],expected)
            avg = result['Inductor']['IL average [A]']
            self.assertAlmostEqual(result['Inductor']['IL RMS [A]']**2,avg**2+expected**2/12)

    def test_transition_phase_controls_ripple(self):
        same_phase = m.calculate_all(replace(m.Constants(),phase_shift=0))
        shifted = m.calculate_all(m.Constants())
        self.assertAlmostEqual(same_phase['Inductor']['IL ripple [App]'],0)
        self.assertGreater(shifted['Inductor']['IL ripple [App]'],0)

    def test_capacitor_formulas(self):
        for vin in (40,20):
            c = replace(m.Constants(),vin=vin,cin_esr=0,cout_esr=0)
            result = m.calculate_all(c)
            op,caps,ind = result['Operating point'],result['Capacitors'],result['Inductor']
            if vin>c.vout:
                duty = op['DA (input HS)']
                self.assertAlmostEqual(caps['Cin RMS current [A]'],op['Iout [A]']*np.sqrt(duty*(1-duty)))
                self.assertAlmostEqual(caps['Cout minimum [F]'],ind['IL ripple [App]']/(8*c.fs*c.allowed_output_ripple))
            else:
                duty = 1-op['DB (output HS)']
                self.assertAlmostEqual(caps['Cout RMS current [A]'],op['Iout [A]']*np.sqrt(duty/(1-duty)))
                self.assertAlmostEqual(caps['Cout minimum [F]'],op['Iout [A]']*duty/(c.fs*c.allowed_output_ripple))

    def test_switched_devices_and_diode_budget(self):
        for vin,count,legs in ((40,2,1),(20,2,1),(30,4,2)):
            c = replace(m.Constants(),vin=vin)
            result = m.calculate_all(c)
            self.assertEqual(result['Gate drive']['switching MOSFET count'],count)
            expected = legs*c.diode_vf*result['Inductor']['IL average [A]']*2*c.dead_time*c.fs
            self.assertAlmostEqual(sum(d['body diode loss [W]'] for key,d in result.items() if key.startswith('MOSFET')),expected)

    def test_load_override_and_core_loss(self):
        c = replace(m.Constants(),load_resistance=60,core_k=1,core_alpha=1,core_beta=2,core_delta_b=0.01,core_volume=1e-6)
        result = m.calculate_all(c)
        self.assertEqual(result['Operating point']['Pout [W]'],15)
        self.assertAlmostEqual(result['Inductor']['inductor core loss [W]'],5e-6)
        self.assertTrue(result['Loss budget']['core loss included'])
        self.assertAlmostEqual(result['Loss budget']['estimated Pin [W]'],15+result['Loss budget']['modeled total loss [W]'])

    def test_thermal_shared_sink(self):
        c = replace(m.Constants(),theta_jc=2,theta_cs=1,theta_sa=4)
        devices = {'Q1':{'total FET loss [W]':1},'Q2':{'total FET loss [W]':2}}
        temperatures = m.calculate_junction_temperatures(c,devices)
        self.assertEqual(temperatures['Q1 junction estimate [degC]'],25+3*4+1*3)

    def test_integrator_convergence_and_settling(self):
        c = m.Constants()
        for vin,da,db in ((40,.75,1),(20,1,2/3),(30,.7,.7)):
            t,y,eq = m.simulate_state_space(c,vin,da,db,duration=.001,step=1e-6)
            tf,yf,_ = m.simulate_state_space(c,vin,da,db,duration=.001,step=.5e-6)
            np.testing.assert_allclose(y[-1],yf[-1],atol=1e-8,rtol=1e-8)
            t,y,eq = m.simulate_state_space(c,vin,da,db)
            np.testing.assert_allclose(y[-1],eq,atol=1e-4,rtol=1e-4)
            self.assertGreater(y[:,0].min(),0)

    def test_switched_simulation_matches_analytical_ripple(self):
        for vin in (40,20,30):
            c = replace(m.Constants(),vin=vin,cout=1,cout_esr=0)  # Stiff, lossless Cout isolates volt-time ripple.
            op,ind = (m.calculate_all(c)[s] for s in ('Operating point','Inductor'))
            sim = m.switching_summary(c,vin,op['DA (input HS)'],op['DB (output HS)'])
            self.assertAlmostEqual(sim['IL ripple [App]'],ind['IL ripple [App]'],places=5)
            self.assertAlmostEqual(sim['IL average [A]'],ind['IL average [A]'],places=5)
        c = replace(m.Constants(),vin=40,cout_esr=0)
        op,caps = (m.calculate_all(c)[s] for s in ('Operating point','Capacitors'))
        sim = m.switching_summary(c,40,op['DA (input HS)'],op['DB (output HS)'])
        self.assertAlmostEqual(sim['Vout ripple [Vpp]'],caps['output capacitive ripple [Vpp]'],delta=0.05*caps['output capacitive ripple [Vpp]'])

    def test_regulated_duties_with_series_resistance(self):
        c = replace(m.Constants(),cout_esr=0)  # Averaged model omits ESR loss.
        rs,r = m.series_resistance(c),m.calculate_load(c)['R_load [ohm]']
        for vin in (40,20,30):
            _,da,db = m.regulated_duties(c,vin)
            state = (c.vout/(db*r),c.vout)
            np.testing.assert_allclose(m.state_space_derivatives(state,vin,da,db,c.inductance,c.cout,r,rs),0,atol=1e-8)
            sim = m.switching_summary(c,vin,da,db,rs)
            self.assertAlmostEqual(sim['Vout average [V]'],c.vout,delta=0.01)
            t,y,eq = m.simulate_state_space(c,vin,da,db,series_r=rs)
            np.testing.assert_allclose(eq,state)
            np.testing.assert_allclose(y[-1],eq,rtol=1e-4)
        with self.assertRaises(ValueError):
            m.regulated_duties(c,31)  # 1.3 V series drop exceeds the 0.5 V window.

    def test_invalid_inputs_and_esr_budget(self):
        for changes in ({'inductance':0},{'fs':-1},{'vin':float('nan')},{'phase_shift':1},{'core_k':1}):
            with self.assertRaises(ValueError):
                m.calculate_all(replace(m.Constants(),**changes))
        result = m.calculate_all(replace(m.Constants(),cout_esr=1))
        self.assertTrue(np.isinf(result['Capacitors']['Cout minimum [F]']))

    def test_cli_csv_and_rejection(self):
        result = subprocess.run([sys.executable,str(PATH),'--no-plot'],input='30,24,30,5,50000,220e-6,100e-6,100e-6\n\n',capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('mode: buck',result.stdout)
        result = subprocess.run([sys.executable,str(PATH),'--defaults','--no-plot','--set','fs=0'],capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('fs must be positive',result.stderr)


if __name__=='__main__':
    unittest.main()
