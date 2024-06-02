# pyPowerWall - Tesla TEDAPI Class
# -*- coding: utf-8 -*-
"""
 Tesla TEADAPI Class
 
 This module allows you to access the Tesla Powerwall Gateway 
 TEDAPI on 192.168.91.1 as used by the Tesla One app.

 Class:
    TEDAPI - Tesla TEDAPI Class

 Functions:
    get_din() - Get the DIN from the Powerwall Gateway
    get_config() - Get the Powerwall Gateway Configuration
    get_status() - Get the Powerwall Gateway Status
    connect() - Connect to the Powerwall Gateway
    backup_time_remaining() - Get the time remaining in hours
    battery_level() - Get the battery level as a percentage
    vitals() - Use tedapi data to create a vitals dictionary

 Note:
    This module requires access to the Powerwall Gateway. You can add a route to
    using the command: sudo route add -host 192.168.91.1 <Powerwall_IP>
    The Powerwall Gateway password is required to access the TEDAPI.

 Author: Jason A. Cox
 Date: 1 Jun 2024
 For more information see https://github.com/jasonacox/pypowerwall
"""

# Imports
import requests
import logging
from . import tedapi_pb2
import requests
from requests.packages.urllib3.exceptions import InsecureRequestWarning
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
import json
import time
from pypowerwall import __version__
import math

# TEDAPI Fixed Gateway IP Address
GW_IP = "192.168.91.1"

# Rate Limit Codes
BUSY_CODES = [429, 503]

# Setup Logging
log = logging.getLogger(__name__)

# Utility Functions
def lookup(data, keylist):
    """
    Lookup a value in a nested dictionary or return None if not found.
        data - nested dictionary
        keylist - list of keys to traverse
    """
    if len(keylist) == 1:
        return data.get(keylist[0])
    for key in keylist:
        if key in data:
            data = data[key]
        else:
            return None
    return data

# TEDAPI Class

class TEDAPI:
    def __init__(self, gw_pwd, debug=False, pwcacheexpire: int = 5, timeout: int = 5):
        self.debug = debug 
        self.pwcachetime = {}  # holds the cached data timestamps for api
        self.pwcacheexpire = pwcacheexpire  # seconds to expire cache
        self.pwcache = {}  # holds the cached data for api
        self.timeout = timeout
        self.pwcooldown = 0
        self.din = None
        if not gw_pwd:
            raise ValueError("Missing gw_pwd")
        if self.debug:
            log.setLevel(logging.DEBUG)
        self.gw_pwd = gw_pwd
        # Connect to Powerwall Gateway
        if not self.connect():
            log.error("Failed to connect to Powerwall Gateway")
            raise ValueError("Failed to connect to Powerwall Gateway")

    # TEDAPI Functions

    def get_din(self, force=False):
        """
        Get the DIN from the Powerwall Gateway
        """
        # Check Cache
        if not force and "din" in self.pwcachetime:
                if time.time() - self.pwcachetime["din"] < self.pwcacheexpire:
                    log.debug("Using Cached DIN")
                    return self.pwcache["din"]
        if not force and self.pwcooldown > time.perf_counter():
            # Rate limited - return None
            log.debug('Rate limit cooldown period - Pausing API calls')
            return None
        # Fetch DIN from Powerwall
        log.debug("Fetching DIN from Powerwall...")
        url = f'https://{GW_IP}/tedapi/din'
        r = requests.get(url, auth=('Tesla_Energy_Device', self.gw_pwd), verify=False)
        if r.status_code in BUSY_CODES:
            # Rate limited - Switch to cooldown mode for 5 minutes
            self.pwcooldown = time.perf_counter() + 300
            log.error('Possible Rate limited by Powerwall at - Activating 5 minute cooldown')
            return None
        if r.status_code != 200:
            log.error(f"Error fetching DIN: {r.status_code}")
            return None
        din = r.text
        log.debug(f"Connected: Powerwall Gateway DIN: {din}")
        self.pwcachetime["din"] = time.time()
        self.pwcache["din"] = din
        return din
    
    def get_config(self,force=False):
        """
        Get the Powerwall Gateway Configuration
        
        Payload:
        {
            "auto_meter_update": true,
            "battery_blocks": [],
            "bridge_inverter": {},
            "client_protocols": {},
            "credentials": [],
            "customer": {},
            "default_real_mode": "self_consumption",
            "dio": {},
            "enable_inverter_meter_readings": true,
            "freq_shift_load_shed": {},
            "freq_support_parameters": {},
            "industrial_networks": {},
            "installer": {},
            "island_config": {},
            "island_contactor_controller": {},
            "logging": {},
            "meters": [],
            "site_info": {},
            "solar": {},
            "solars": [],
            "strategy": {},
            "test_timers": {},
            "vin": "1232100-00-E--TG11234567890"
        }
        """
        # Check Cache
        if not force and "config" in self.pwcachetime:
            if time.time() - self.pwcachetime["config"] < self.pwcacheexpire:
                log.debug("Using Cached Payload")
                return self.pwcache["config"]
        if not force and self.pwcooldown > time.perf_counter():
                # Rate limited - return None
                log.debug('Rate limit cooldown period - Pausing API calls')
                return None
        # Fetch Configuration from Powerwall
        log.debug("Get Configuration from Powerwall")
        # Build Protobuf to fetch config
        pb = tedapi_pb2.Message()
        pb.message.deliveryChannel = 1
        pb.message.sender.local = 1
        pb.message.recipient.din = self.din  # DIN of Powerwall
        pb.message.config.send.num = 1
        pb.message.config.send.file = "config.json"
        pb.tail.value = 1
        url = f'https://{GW_IP}/tedapi/v1'
        r = requests.post(url, auth=('Tesla_Energy_Device', self.gw_pwd), verify=False,
            headers={'Content-type': 'application/octet-string'},
            data=pb.SerializeToString())
        log.debug(f"Response Code: {r.status_code}")
        if r.status_code in BUSY_CODES:
            # Rate limited - Switch to cooldown mode for 5 minutes
            self.pwcooldown = time.perf_counter() + 300
            log.error('Possible Rate limited by Powerwall at - Activating 5 minute cooldown')
            return None
        if r.status_code != 200:
            log.error(f"Error fetching config: {r.status_code}")
            return None
        # Decode response
        tedapi = tedapi_pb2.Message()
        tedapi.ParseFromString(r.content)
        payload = tedapi.message.config.recv.file.text
        try:
            data = json.loads(payload)
        except json.JSONDecodeError as e:
            log.error(f"Error Decoding JSON: {e}")
            data = {}
        log.debug(f"Configuration: {data}")
        self.pwcachetime["config"] = time.time()
        self.pwcache["config"] = data
        return data

    def get_status(self, force=False):
        """
        Get the Powerwall Gateway Status

        Payload:
        {
            "control": {
                "alerts": {},
                "batteryBlocks": [],
                "islanding": {},
                "meterAggregates": [],
                "pvInverters": [],
                "siteShutdown": {},
                "systemStatus": {}
                },
            "esCan": {
                "bus": {
                    "ISLANDER": {},
                    "MSA": {},
                    "PINV": [],
                    "POD": [],
                    "PVAC": [],
                    "PVS": [],
                    "SYNC": {},
                    "THC": []
                    },
                "enumeration": null,
                "firmwareUpdate": {},
                "inverterSelfTests": null,
                "phaseDetection": null
                },
            "neurio": {
                "isDetectingWiredMeters": false,
                "pairings": [],
                "readings": []
                },
            "pw3Can": {},
            "system": {}
        }

        """
        # Check Cache
        if not force and "status" in self.pwcachetime:
            if time.time() - self.pwcachetime["status"] < self.pwcacheexpire:
                log.debug("Using Cached Payload")
                return self.pwcache["status"]
        if not force and self.pwcooldown > time.perf_counter():
                # Rate limited - return None
                log.debug('Rate limit cooldown period - Pausing API calls')
                return None
        # Fetch Current Status from Powerwall
        log.debug("Get Status from Powerwall")
        # Build Protobuf to fetch status
        pb = tedapi_pb2.Message()
        pb.message.deliveryChannel = 1
        pb.message.sender.local = 1
        pb.message.recipient.din = self.din  # DIN of Powerwall
        pb.message.payload.send.num = 2
        pb.message.payload.send.payload.value = 1
        pb.message.payload.send.payload.text = " query DeviceControllerQuery {\n  control {\n    systemStatus {\n        nominalFullPackEnergyWh\n        nominalEnergyRemainingWh\n    }\n    islanding {\n        customerIslandMode\n        contactorClosed\n        microGridOK\n        gridOK\n    }\n    meterAggregates {\n      location\n      realPowerW\n    }\n    alerts {\n      active\n    },\n    siteShutdown {\n      isShutDown\n      reasons\n    }\n    batteryBlocks {\n      din\n      disableReasons\n    }\n    pvInverters {\n      din\n      disableReasons\n    }\n  }\n  system {\n    time\n    sitemanagerStatus {\n      isRunning\n    }\n    updateUrgencyCheck  {\n      urgency\n      version {\n        version\n        gitHash\n      }\n      timestamp\n    }\n  }\n  neurio {\n    isDetectingWiredMeters\n    readings {\n      serial\n      dataRead {\n        voltageV\n        realPowerW\n        reactivePowerVAR\n        currentA\n      }\n      timestamp\n    }\n    pairings {\n      serial\n      shortId\n      status\n      errors\n      macAddress\n      isWired\n      modbusPort\n      modbusId\n      lastUpdateTimestamp\n    }\n  }\n  pw3Can {\n    firmwareUpdate {\n      isUpdating\n      progress {\n         updating\n         numSteps\n         currentStep\n         currentStepProgress\n         progress\n      }\n    }\n  }\n  esCan {\n    bus {\n      PVAC {\n        packagePartNumber\n        packageSerialNumber\n        subPackagePartNumber\n        subPackageSerialNumber\n        PVAC_Status {\n          isMIA\n          PVAC_Pout\n          PVAC_State\n          PVAC_Vout\n          PVAC_Fout\n        }\n        PVAC_InfoMsg {\n          PVAC_appGitHash\n        }\n        PVAC_Logging {\n          isMIA\n          PVAC_PVCurrent_A\n          PVAC_PVCurrent_B\n          PVAC_PVCurrent_C\n          PVAC_PVCurrent_D\n          PVAC_PVMeasuredVoltage_A\n          PVAC_PVMeasuredVoltage_B\n          PVAC_PVMeasuredVoltage_C\n          PVAC_PVMeasuredVoltage_D\n          PVAC_VL1Ground\n          PVAC_VL2Ground\n        }\n        alerts {\n          isComplete\n          isMIA\n          active\n        }\n      }\n      PINV {\n        PINV_Status {\n          isMIA\n          PINV_Fout\n          PINV_Pout\n          PINV_Vout\n          PINV_State\n          PINV_GridState\n        }\n        PINV_AcMeasurements {\n          isMIA\n          PINV_VSplit1\n          PINV_VSplit2\n        }\n        PINV_PowerCapability {\n          isComplete\n          isMIA\n          PINV_Pnom\n        }\n        alerts {\n          isComplete\n          isMIA\n          active\n        }\n      }\n      PVS {\n        PVS_Status {\n          isMIA\n          PVS_State\n          PVS_vLL\n          PVS_StringA_Connected\n          PVS_StringB_Connected\n          PVS_StringC_Connected\n          PVS_StringD_Connected\n          PVS_SelfTestState\n        }\n        alerts {\n          isComplete\n          isMIA\n          active\n        }\n      }\n      THC {\n        packagePartNumber\n        packageSerialNumber\n        THC_InfoMsg {\n          isComplete\n          isMIA\n          THC_appGitHash\n        }\n        THC_Logging {\n          THC_LOG_PW_2_0_EnableLineState\n        }\n      }\n      POD {\n        POD_EnergyStatus {\n          isMIA\n          POD_nom_energy_remaining\n          POD_nom_full_pack_energy\n        }\n        POD_InfoMsg {\n            POD_appGitHash\n        }\n      }\n      MSA {\n        packagePartNumber\n        packageSerialNumber\n        MSA_InfoMsg {\n          isMIA\n          MSA_appGitHash\n          MSA_assemblyId\n        }\n        METER_Z_AcMeasurements {\n          isMIA\n          lastRxTime\n          METER_Z_CTA_InstRealPower\n          METER_Z_CTA_InstReactivePower\n          METER_Z_CTA_I\n          METER_Z_VL1G\n          METER_Z_CTB_InstRealPower\n          METER_Z_CTB_InstReactivePower\n          METER_Z_CTB_I\n          METER_Z_VL2G\n        }\n        MSA_Status {\n          lastRxTime\n        }\n      }\n      SYNC {\n        packagePartNumber\n        packageSerialNumber\n        SYNC_InfoMsg {\n          isMIA\n          SYNC_appGitHash\n        }\n        METER_X_AcMeasurements {\n          isMIA\n          isComplete\n          lastRxTime\n          METER_X_CTA_InstRealPower\n          METER_X_CTA_InstReactivePower\n          METER_X_CTA_I\n          METER_X_VL1N\n          METER_X_CTB_InstRealPower\n          METER_X_CTB_InstReactivePower\n          METER_X_CTB_I\n          METER_X_VL2N\n          METER_X_CTC_InstRealPower\n          METER_X_CTC_InstReactivePower\n          METER_X_CTC_I\n          METER_X_VL3N\n        }\n        METER_Y_AcMeasurements {\n          isMIA\n          isComplete\n          lastRxTime\n          METER_Y_CTA_InstRealPower\n          METER_Y_CTA_InstReactivePower\n          METER_Y_CTA_I\n          METER_Y_VL1N\n          METER_Y_CTB_InstRealPower\n          METER_Y_CTB_InstReactivePower\n          METER_Y_CTB_I\n          METER_Y_VL2N\n          METER_Y_CTC_InstRealPower\n          METER_Y_CTC_InstReactivePower\n          METER_Y_CTC_I\n          METER_Y_VL3N\n        }\n        SYNC_Status {\n          lastRxTime\n        }\n      }\n      ISLANDER {\n        ISLAND_GridConnection {\n          ISLAND_GridConnected\n          isComplete\n        }\n        ISLAND_AcMeasurements {\n          ISLAND_VL1N_Main\n          ISLAND_FreqL1_Main\n          ISLAND_VL2N_Main\n          ISLAND_FreqL2_Main\n          ISLAND_VL3N_Main\n          ISLAND_FreqL3_Main\n          ISLAND_VL1N_Load\n          ISLAND_FreqL1_Load\n          ISLAND_VL2N_Load\n          ISLAND_FreqL2_Load\n          ISLAND_VL3N_Load\n          ISLAND_FreqL3_Load\n          ISLAND_GridState\n          lastRxTime\n          isComplete\n          isMIA\n        }\n      }\n    }\n    enumeration {\n      inProgress\n      numACPW\n      numPVI\n    }\n    firmwareUpdate {\n      isUpdating\n      powerwalls {\n        updating\n        numSteps\n        currentStep\n        currentStepProgress\n        progress\n      }\n      msa {\n        updating\n        numSteps\n        currentStep\n        currentStepProgress\n        progress\n      }\n      sync {\n        updating\n        numSteps\n        currentStep\n        currentStepProgress\n        progress\n      }\n      pvInverters {\n        updating\n        numSteps\n        currentStep\n        currentStepProgress\n        progress\n      }\n    }\n    phaseDetection {\n      inProgress\n      lastUpdateTimestamp\n      powerwalls {\n        din\n        progress\n        phase\n      }\n    }\n    inverterSelfTests {\n      isRunning\n      isCanceled\n      pinvSelfTestsResults {\n        din\n        overall {\n          status\n          test\n          summary\n          setMagnitude\n          setTime\n          tripMagnitude\n          tripTime\n          accuracyMagnitude\n          accuracyTime\n          currentMagnitude\n          timestamp\n          lastError\n        }\n        testResults {\n          status\n          test\n          summary\n          setMagnitude\n          setTime\n          tripMagnitude\n          tripTime\n          accuracyMagnitude\n          accuracyTime\n          currentMagnitude\n          timestamp\n          lastError\n        }\n      }\n    }\n  }\n}\n"
        pb.message.payload.send.code = b'0\201\206\002A\024\261\227\245\177\255\265\272\321r\032\250\275j\305\030\2300\266\022B\242\264pO\262\024vd\267\316\032\f\376\322V\001\f\177*\366\345\333g_/`\v\026\225_qc\023$\323\216y\276~\335A1\022x\002Ap\a_\264\037]\304>\362\356\005\245V\301\177*\b\307\016\246]\037\202\242\353I~\332\317\021\336\006\033q\317\311\264\315\374\036\365s\272\225\215#o!\315z\353\345z\226\365\341\f\265\256r\373\313/\027\037'
        pb.message.payload.send.b.value = "{}"
        pb.tail.value = 1
        url = f'https://{GW_IP}/tedapi/v1'
        r = requests.post(url, auth=('Tesla_Energy_Device', self.gw_pwd), verify=False,
            headers={'Content-type': 'application/octet-string'},
            data=pb.SerializeToString())
        log.debug(f"Response Code: {r.status_code}")
        if r.status_code in BUSY_CODES:
            # Rate limited - Switch to cooldown mode for 5 minutes
            self.pwcooldown = time.perf_counter() + 300
            log.error('Possible Rate limited by Powerwall at - Activating 5 minute cooldown')
            return None
        if r.status_code != 200:
            log.error(f"Error fetching status: {r.status_code}")
            return None
        # Decode response
        tedapi = tedapi_pb2.Message()
        tedapi.ParseFromString(r.content)
        payload = tedapi.message.payload.recv.text
        try:
            data = json.loads(payload)
        except json.JSONDecodeError as e:
            log.error(f"Error Decoding JSON: {e}")
            data = {}
        log.debug(f"Status: {data}")
        self.pwcachetime["status"] = time.time()
        self.pwcache["status"] = data
        return data

    def connect(self):
        """
        Connect to the Powerwall Gateway
        """
        # Test IP Connection to Powerwall Gateway
        log.debug(f"Testing Connection to Powerwall Gateway: {GW_IP}")
        url = f'https://{GW_IP}'
        try:
            r = requests.get(url, verify=False, timeout=5)
        except requests.exceptions.RequestException as e:
            r = False
            log.error("ERROR: Powerwall not Found",
                      f"Try: sudo route add -host <Powerwall_IP> {GW_IP}")
        if r:
            # Attempt to fetch DIN from Powerwall
            self.din = self.get_din()
            return True
        self.din = None
        return False

    # Handy Function to access Powerwall Status

    def backup_time_remaining(self, force=False):
        """
        Get the time remaining in hours
        """
        status = self.get_status(force)
        nominalEnergyRemainingWh = lookup(status, ['control', 'systemStatus', 'nominalEnergyRemainingWh'])
        power = lookup(status, ['control', 'meterAggregates', 0, 'realPowerW'])
        if not nominalEnergyRemainingWh or not power:
            return None
        time_remaining = nominalEnergyRemainingWh / power 
        return time_remaining
    
    def battery_level(self, force=False):
        """
        Get the battery level as a percentage
        """
        status = self.get_status(force)
        nominalEnergyRemainingWh = lookup(status, ['control', 'systemStatus', 'nominalEnergyRemainingWh'])
        nominalFullPackEnergyWh = lookup(status, ['control', 'systemStatus', 'nominalFullPackEnergyWh'])
        if not nominalEnergyRemainingWh or not nominalFullPackEnergyWh:
            return None
        battery_level = nominalEnergyRemainingWh / nominalFullPackEnergyWh * 100
        return battery_level

    
    # Vitals API Mapping Function

    def vitals(self, force=False):
        """
        Use tedapi data to create a vitals API dictionary 
        """
        def calculate_ac_power(Vpeak, Ipeak):
            Vrms = Vpeak / math.sqrt(2)
            Irms = Ipeak / math.sqrt(2)
            power = Vrms * Irms
            return power
        
        def calculate_dc_power(V, I):
            power = V * I
            return power

        status = self.get_status(force)
        config = self.get_config(force)

        if not status or not config:
            return None

        # Create Header
        tesla = {}
        header = {}
        header["VITALS"] = {
            "text": "Device vitals generated from Tesla Powerwall Gateway TEDAPI",
            "timestamp": time.time(),
            "gateway": GW_IP,
            "pyPowerwall": __version__,
        }
            
        # Create NEURIO block
        neurio = {}
        c = 1000
        # Loop through each Neurio device serial number
        for n in lookup(status, ['neurio', 'readings']) or {}:
            # Loop through each CT on the Neurio device
            sn = n.get('serial', str(c))
            cts = {}
            i = 0
            c = c + 1
            for ct in n['dataRead'] or {}:
                device = f"NEURIO_CT{i}_"
                cts[device + "InstRealPower"] = ct['realPowerW']
                cts[device + "Location"] = "solarRGM"
                i = i + 1
            rest = {
                "componentParentDin": lookup(config, ['vin']),
                "firmwareVersion": None,
                "lastCommunicationTime": n.get('timestamp', None),
                "manufacturer": "NEURIO",
                "meterAttributes": {
                    "meterLocation": []
                },
                "serialNumber": sn
            }
            neurio[f"NEURIO--{sn}"] = {**cts, **rest}
            
        # Create PVAC, PVS, and TESLA blocks - Assume the are aligned
        pvac = {}
        pvs = {}
        tesla = {}
        i = 0
        num = len(lookup(status, ['esCan', 'bus', 'PVAC']))
        if num != len(lookup(status, ['esCan', 'bus', 'PVS'])):
            log.warning("PVAC and PVS device count mismatch")
        # Loop through each device serial number
        for p in lookup(status, ['esCan', 'bus', 'PVAC']) or {}:
            if not p['packageSerialNumber']:
                continue
            packagePartNumber = p.get('packagePartNumber', str(i))
            packageSerialNumber = p.get('packageSerialNumber', str(i))
            pvac_name = f"PVAC--{packagePartNumber}--{packageSerialNumber}"
            V_A = p['PVAC_Logging']['PVAC_PVMeasuredVoltage_A']
            V_B = p['PVAC_Logging']['PVAC_PVMeasuredVoltage_B']
            V_C = p['PVAC_Logging']['PVAC_PVMeasuredVoltage_C']
            V_D = p['PVAC_Logging']['PVAC_PVMeasuredVoltage_D']
            I_A = p['PVAC_Logging']['PVAC_PVCurrent_A']
            I_B = p['PVAC_Logging']['PVAC_PVCurrent_B']
            I_C = p['PVAC_Logging']['PVAC_PVCurrent_C']
            I_D = p['PVAC_Logging']['PVAC_PVCurrent_D']
            P_A = calculate_dc_power(V_A, I_A)
            P_B = calculate_dc_power(V_B, I_B)
            P_C = calculate_dc_power(V_C, I_C)
            P_D = calculate_dc_power(V_D, I_D)
            pvac[pvac_name] = {
                "PVAC_Fout": lookup(p, ['PVAC_Status', 'PVAC_Fout']),
                "PVAC_GridState": None,
                "PVAC_InvState": None,
                "PVAC_Iout": None,
                "PVAC_LifetimeEnergyPV_Total": None,
                "PVAC_PVCurrent_A": I_A,
                "PVAC_PVCurrent_B": I_B,
                "PVAC_PVCurrent_C": I_C,
                "PVAC_PVCurrent_D": I_D,
                "PVAC_PVMeasuredPower_A": P_A, # computed
                "PVAC_PVMeasuredPower_B": P_B, # computed
                "PVAC_PVMeasuredPower_C": P_C, # computed
                "PVAC_PVMeasuredPower_D": P_D, # computed
                "PVAC_PVMeasuredVoltage_A": V_A,
                "PVAC_PVMeasuredVoltage_B": V_B,
                "PVAC_PVMeasuredVoltage_C": V_C,
                "PVAC_PVMeasuredVoltage_D": V_D,
                "PVAC_Pout": lookup(p, ['PVAC_Status', 'PVAC_Pout']),
                "PVAC_PvState_A": None, # These are placeholders
                "PVAC_PvState_B": None, # Compute from PVS below
                "PVAC_PvState_C": None, # PV_Disabled, PV_Active, PV_Active_Parallel
                "PVAC_PvState_D": None, # Not available in TEDAPI
                "PVAC_Qout": None,
                "PVAC_State": lookup(p, ['PVAC_Status', 'PVAC_State']),
                "PVAC_VHvMinusChassisDC": None,
                "PVAC_VL1Ground": lookup(p, ['PVAC_Logging', 'PVAC_VL1Ground']),
                "PVAC_VL2Ground": lookup(p, ['PVAC_Logging', 'PVAC_VL2Ground']),
                "PVAC_Vout": lookup(p, ['PVAC_Status', 'PVAC_Vout']),
                "PVI-PowerStatusSetpoint": None,
                "componentParentDin": None, # TODO: map to TETHC
                "firmwareVersion": None,
                "lastCommunicationTime": None,
                "manufacturer": "TESLA",
                "partNumber": packagePartNumber,
                "serialNumber": packageSerialNumber,
                "teslaEnergyEcuAttributes": {
                    "ecuType": 296
                }
            }
            pvs_name = f"PVS--{packagePartNumber}--{packageSerialNumber}"
            pvs_data = lookup(status, ['esCan', 'bus', 'PVS'])
            if i < len(pvs_data):
                pvs_data = pvs_data[i]
                # Set String Connected states
                string_a = lookup(pvs_data, ['PVS_Status', 'PVS_StringA_Connected'])
                string_b = lookup(pvs_data, ['PVS_Status', 'PVS_StringB_Connected'])
                string_c = lookup(pvs_data, ['PVS_Status', 'PVS_StringC_Connected'])
                string_d = lookup(pvs_data, ['PVS_Status', 'PVS_StringD_Connected'])
                # Set PVAC PvState based on PVS String Connected states
                pvac[pvac_name]["PVAC_PvState_A"] = "PV_Active" if string_a else "PV_Disabled"
                pvac[pvac_name]["PVAC_PvState_B"] = "PV_Active" if string_b else "PV_Disabled"
                pvac[pvac_name]["PVAC_PvState_C"] = "PV_Active" if string_c else "PV_Disabled"
                pvac[pvac_name]["PVAC_PvState_D"] = "PV_Active" if string_d else "PV_Disabled"
                pvs[pvs_name] = {
                    "PVS_EnableOutput": None,
                    "PVS_SelfTestState": lookup(pvs_data, ['PVS_Status', 'PVS_SelfTestState']),
                    "PVS_State": lookup(pvs_data, ['PVS_Status', 'PVS_State']),
                    "PVS_StringA_Connected": string_a,
                    "PVS_StringB_Connected": string_b,
                    "PVS_StringC_Connected": string_c,
                    "PVS_StringD_Connected": string_d,
                    "PVS_vLL": lookup(pvs_data, ['PVS_Status', 'PVS_vLL']),
                    "alerts": lookup(pvs_data, ['alerts', 'active']) or [],
                    "componentParentDin": pvac_name,
                    "firmwareVersion": None,
                    "lastCommunicationTime": None,
                    "manufacturer": "TESLA",
                    "partNumber": packagePartNumber,
                    "serialNumber": packageSerialNumber,
                    "teslaEnergyEcuAttributes": {
                        "ecuType": 297
                    }
                }
            tesla_name = f"TESLA--{packagePartNumber}--{packageSerialNumber}"
            if i < len(config.get('solars', [{}])):
                tesla_nameplate = config['solars'][i].get('power_rating_watts', None)
                brand = config['solars'][i].get('brand', None)
            else:
                tesla_nameplate = None
                brand = None
            tesla[tesla_name] = {
                "componentParentDin": f"STSTSM--{lookup(config, ['vin'])}",
                "firmwareVersion": None,
                "lastCommunicationTime": None,
                "manufacturer": brand.upper() if brand else "TESLA",
                "pvInverterAttributes": {
                    "nameplateRealPowerW": tesla_nameplate,
                },
                "serialNumber": f"{packagePartNumber}--{packageSerialNumber}",
            }
            i = i + 1

        # Create STSTSM block
        name = f"STSTSM--{lookup(config, ['vin'])}"
        ststsm = {}
        ststsm[name] =  {
            "STSTSM-Location": "Gateway",
            "alerts": lookup(status, ['control', 'alerts', 'active']) or [],
            "firmwareVersion": None,
            "lastCommunicationTime": None,
            "manufacturer": "TESLA",
            "partNumber": lookup(config, ['vin']).split('--')[0],
            "serialNumber": lookup(config, ['vin']).split('--')[-1],
            "teslaEnergyEcuAttributes": {
                "ecuType": 207
            }
        }
        
        # Create TETHC, TEPINV and TEPOD blocks
        tethc = {} # parent
        tepinv = {}
        tepod = {}
        i = 0
        # Loop through each THC device serial number
        for p in lookup(status, ['esCan', 'bus', 'THC']) or {}:
            if not p['packageSerialNumber']:
                continue
            packagePartNumber = p.get('packagePartNumber', str(i))
            packageSerialNumber = p.get('packageSerialNumber', str(i))
            # TETHC block
            parent_name = f"TETHC--{packagePartNumber}--{packageSerialNumber}"
            tethc[parent_name] = {
                "THC_AmbientTemp": None,
                "THC_State": None,
                "alerts": [],
                "componentParentDin": f"STSTSM--{lookup(config, ['vin'])}",
                "firmwareVersion": None,
                "lastCommunicationTime": None,
                "manufacturer": "TESLA",
                "partNumber": packagePartNumber,
                "serialNumber": packageSerialNumber,
                "teslaEnergyEcuAttributes": {
                    "ecuType": 224
                }
            }
            # TEPOD block
            name = f"TEPOD--{packagePartNumber}--{packageSerialNumber}"
            pod = lookup(status, ['esCan', 'bus', 'POD'])[i]
            energy_remaining = lookup(pod, ['POD_EnergyStatus', 'POD_nom_energy_remaining'])
            full_pack_energy = lookup(pod, ['POD_EnergyStatus', 'POD_nom_full_pack_energy'])
            if energy_remaining and full_pack_energy:
                energy_to_be_charged = full_pack_energy - energy_remaining
            else:
                energy_to_be_charged = None
            tepod[name] = {
                "POD_ActiveHeating": None,
                "POD_CCVhold": None,
                "POD_ChargeComplete": None,
                "POD_ChargeRequest": None,
                "POD_DischargeComplete": None,
                "POD_PermanentlyFaulted": None,
                "POD_PersistentlyFaulted": None,
                "POD_available_charge_power": None,
                "POD_available_dischg_power": None,
                "POD_enable_line": None,
                "POD_nom_energy_remaining": energy_remaining,
                "POD_nom_energy_to_be_charged": energy_to_be_charged, #computed
                "POD_nom_full_pack_energy": full_pack_energy,
                "POD_state": None,
                "alerts": lookup(p, ['alerts', 'active']) or [],
                "componentParentDin": parent_name,
                "firmwareVersion": None,
                "lastCommunicationTime": None,
                "manufacturer": "TESLA",
                "partNumber": packagePartNumber,
                "serialNumber": packageSerialNumber,
                "teslaEnergyEcuAttributes": {
                    "ecuType": 226
                }
            }
            # TEPINV block
            name = f"TEPINV--{packagePartNumber}--{packageSerialNumber}"
            pinv = lookup(status, ['esCan', 'bus', 'PINV'])[i]
            tepinv[name] = {
                "PINV_EnergyCharged": None,
                "PINV_EnergyDischarged": None,
                "PINV_Fout": lookup(pinv, ['PINV_Status', 'PINV_Fout']),
                "PINV_GridState": lookup(p, ['PINV_Status', 'PINV_GridState']),
                "PINV_HardwareEnableLine": None,
                "PINV_PllFrequency": None,
                "PINV_PllLocked": None,
                "PINV_Pout": lookup(pinv, ['PINV_Status', 'PINV_Pout']),
                "PINV_PowerLimiter": None,
                "PINV_Qout": None,
                "PINV_ReadyForGridForming": None,
                "PINV_State": lookup(pinv, ['PINV_Status', 'PINV_State']),
                "PINV_VSplit1": lookup(pinv, ['PINV_AcMeasurements', 'PINV_VSplit1']),
                "PINV_VSplit2": lookup(pinv, ['PINV_AcMeasurements', 'PINV_VSplit2']),
                "PINV_Vout": lookup(pinv, ['PINV_Status', 'PINV_Vout']),
                "alerts": lookup(pinv, ['alerts', 'active']) or [],
                "componentParentDin": parent_name,
                "firmwareVersion": None,
                "lastCommunicationTime": None,
                "manufacturer": "TESLA",
                "partNumber": packagePartNumber,
                "serialNumber": packageSerialNumber,
                "teslaEnergyEcuAttributes": {
                    "ecuType": 253
                }
            }
            i = i + 1

        # Create TESYNC block
        tesync = {}
        sync = lookup(status, ['esCan', 'bus', 'SYNC'])
        islander = lookup(status, ['esCan', 'bus', 'ISLANDER'])
        packagePartNumber = sync.get('packagePartNumber', None)
        packageSerialNumber = sync.get('packageSerialNumber', None)
        name = f"TESYNC--{packagePartNumber}--{packageSerialNumber}"
        tesync[name] = {
            "ISLAND_FreqL1_Load": lookup(islander, ['ISLAND_AcMeasurements', 'ISLAND_FreqL1_Load']),
            "ISLAND_FreqL1_Main": lookup(islander, ['ISLAND_AcMeasurements', 'ISLAND_FreqL1_Main']),
            "ISLAND_FreqL2_Load": lookup(islander, ['ISLAND_AcMeasurements', 'ISLAND_FreqL2_Load']),
            "ISLAND_FreqL2_Main": lookup(islander, ['ISLAND_AcMeasurements', 'ISLAND_FreqL2_Main']),
            "ISLAND_FreqL3_Load": lookup(islander, ['ISLAND_AcMeasurements', 'ISLAND_FreqL3_Load']),
            "ISLAND_FreqL3_Main": lookup(islander, ['ISLAND_AcMeasurements', 'ISLAND_FreqL3_Main']),
            "ISLAND_GridConnected": lookup(islander, ['ISLAND_GridConnection', 'ISLAND_GridConnected']),
            "ISLAND_GridState": lookup(islander, ['ISLAND_AcMeasurements', 'ISLAND_GridState']),
            "ISLAND_L1L2PhaseDelta": None,
            "ISLAND_L1L3PhaseDelta": None,
            "ISLAND_L1MicrogridOk": None,
            "ISLAND_L2L3PhaseDelta": None,
            "ISLAND_L2MicrogridOk": None,
            "ISLAND_L3MicrogridOk": None,
            "ISLAND_PhaseL1_Main_Load": None,
            "ISLAND_PhaseL2_Main_Load": None,
            "ISLAND_PhaseL3_Main_Load": None,
            "ISLAND_ReadyForSynchronization": None,
            "ISLAND_VL1N_Load": lookup(islander, ['ISLAND_AcMeasurements', 'ISLAND_VL1N_Load']),
            "ISLAND_VL1N_Main": lookup(islander, ['ISLAND_AcMeasurements', 'ISLAND_VL1N_Main']),
            "ISLAND_VL2N_Load": lookup(islander, ['ISLAND_AcMeasurements', 'ISLAND_VL2N_Load']),
            "ISLAND_VL2N_Main": lookup(islander, ['ISLAND_AcMeasurements', 'ISLAND_VL2N_Main']),
            "ISLAND_VL3N_Load": lookup(islander, ['ISLAND_AcMeasurements', 'ISLAND_VL3N_Load']),
            "ISLAND_VL3N_Main": lookup(islander, ['ISLAND_AcMeasurements', 'ISLAND_VL3N_Main']),
            "METER_X_CTA_I": lookup(sync, ['METER_X_AcMeasurements', 'METER_X_CTA_I']),
            "METER_X_CTA_InstReactivePower": lookup(sync, ['METER_X_AcMeasurements', 'METER_X_CTA_InstReactivePower']),
            "METER_X_CTA_InstRealPower": lookup(sync, ['METER_X_AcMeasurements', 'METER_X_CTA_InstRealPower']),
            "METER_X_CTB_I": lookup(sync, ['METER_X_AcMeasurements', 'METER_X_CTB_I']),
            "METER_X_CTB_InstReactivePower": lookup(sync, ['METER_X_AcMeasurements', 'METER_X_CTB_InstReactivePower']),
            "METER_X_CTB_InstRealPower": lookup(sync, ['METER_X_AcMeasurements', 'METER_X_CTB_InstRealPower']),
            "METER_X_CTC_I": lookup(sync, ['METER_X_AcMeasurements', 'METER_X_CTC_I']),
            "METER_X_CTC_InstReactivePower": lookup(sync, ['METER_X_AcMeasurements', 'METER_X_CTC_InstReactivePower']),
            "METER_X_CTC_InstRealPower": lookup(sync, ['METER_X_AcMeasurements', 'METER_X_CTC_InstRealPower']),
            "METER_X_LifetimeEnergyExport": lookup(sync, ['METER_X_AcMeasurements', 'METER_X_LifetimeEnergyExport']),
            "METER_X_LifetimeEnergyImport": lookup(sync, ['METER_X_AcMeasurements', 'METER_X_LifetimeEnergyImport']),
            "METER_X_VL1N": lookup(sync, ['METER_X_AcMeasurements', 'METER_X_VL1N']),
            "METER_X_VL2N": lookup(sync, ['METER_X_AcMeasurements', 'METER_X_VL2N']),
            "METER_X_VL3N": lookup(sync, ['METER_X_AcMeasurements', 'METER_X_VL3N']),
            "METER_Y_CTA_I": lookup(sync, ['METER_Y_AcMeasurements', 'METER_Y_CTA_I']),
            "METER_Y_CTA_InstReactivePower": lookup(sync, ['METER_Y_AcMeasurements', 'METER_Y_CTA_InstReactivePower']),
            "METER_Y_CTA_InstRealPower": lookup(sync, ['METER_Y_AcMeasurements', 'METER_Y_CTA_InstRealPower']),
            "METER_Y_CTB_I": lookup(sync, ['METER_Y_AcMeasurements', 'METER_Y_CTB_I']),
            "METER_Y_CTB_InstReactivePower": lookup(sync, ['METER_Y_AcMeasurements', 'METER_Y_CTB_InstReactivePower']),
            "METER_Y_CTB_InstRealPower": lookup(sync, ['METER_Y_AcMeasurements', 'METER_Y_CTB_InstRealPower']),
            "METER_Y_CTC_I": lookup(sync, ['METER_Y_AcMeasurements', 'METER_Y_CTC_I']),
            "METER_Y_CTC_InstReactivePower": lookup(sync, ['METER_Y_AcMeasurements', 'METER_Y_CTC_InstReactivePower']),
            "METER_Y_CTC_InstRealPower": lookup(sync, ['METER_Y_AcMeasurements', 'METER_Y_CTC_InstRealPower']),
            "METER_Y_LifetimeEnergyExport": lookup(sync, ['METER_Y_AcMeasurements', 'METER_Y_LifetimeEnergyExport']),
            "METER_Y_LifetimeEnergyImport": lookup(sync, ['METER_Y_AcMeasurements', 'METER_Y_LifetimeEnergyImport']),
            "METER_Y_VL1N": lookup(sync, ['METER_Y_AcMeasurements', 'METER_Y_VL1N']),
            "METER_Y_VL2N": lookup(sync, ['METER_Y_AcMeasurements', 'METER_Y_VL2N']),
            "METER_Y_VL3N": lookup(sync, ['METER_Y_AcMeasurements', 'METER_Y_VL3N']),
            "SYNC_ExternallyPowered": None,
            "SYNC_SiteSwitchEnabled": None,
            "alerts": [],
            "componentParentDin": None,
            "firmwareVersion": None,
            "manufacturer": "TESLA",
            "partNumber": packagePartNumber,
            "serialNumber": packageSerialNumber,
            "teslaEnergyEcuAttributes": {
                "ecuType": 259
            }
        }

        # Create TESLA block - tied to TESYNC
        name = f"TESLA--{packageSerialNumber}"
        tesla[name] = {
                "componentParentDin": f"STSTSM--{lookup(config, ['vin'])}",
                "lastCommunicationTime": None,
                "manufacturer": "TESLA",
                "meterAttributes": {
                    "meterLocation": [
                        1
                    ]
                },
                "serialNumber": packageSerialNumber
            }

        # Create Vitals Dictionary
        vitals = {
            **header,
            **neurio,
            **pvac,
            **pvs,
            **ststsm,
            **tepinv,
            **tepod,
            **tesla,
            **tesync,
            **tethc,
        }
        return vitals
    
    # End of TEDAPI Class
