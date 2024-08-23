import datetime
import dotenv
import os
import requests
import time
import traceback
import urllib3
from asterisk.ami import AMIClient, EventListener, SimpleAction
from xml.sax.saxutils import escape

# Ignore SSL warnings, as all phone certificates have MAC as their CN
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

dotenv.load_dotenv()

PARKING_LOT = int(os.getenv('PARKING_LOT'))
PARKING_SPACES = int(os.getenv('PARKING_SPACES'))
THRESHOLD = int(os.getenv('THRESHOLD'))
BLACKLIST_IP = os.getenv('BLACKLIST_IP').split(' ')

FREEPBX_HOST = os.getenv('HOST')

AMI_USER = os.getenv('AMI_USER')
AMI_PASSWORD = os.getenv('AMI_PASSWORD')

client = AMIClient(address='127.0.0.1', port=5038, timeout=None)
client.login(username=AMI_USER, secret=AMI_PASSWORD)

aor = set()
parked_calls = dict()

def event_listener(event, **kwargs):
    global aor, parked_calls
    try:
        if (event.name == "ParkedCall" and "ActionID" in event):
            parked_calls[event["ParkingSpace"]] = {"Name": event["ParkeeCallerIDName"], "Duration": event["ParkingDuration"]}
        if (event.name == "ParkedCallsComplete"):
            
            pastthreshold = []
            
            for i in range(PARKING_LOT + 1, PARKING_LOT + PARKING_SPACES + 1):
                if str(i) in parked_calls.keys():
                    if int(parked_calls[str(i)]["Duration"]) > THRESHOLD:
                        pastthreshold.append(i - PARKING_LOT)

            parked_calls_xml = "<?xml version='1.0' encoding='ISO-8859-1' ?><YealinkIPPhoneStatus Beep=\"" + ("no" if len(pastthreshold) == 0 else "yes") + """" Timeout="15">"""

           
            for i in range(PARKING_LOT + 1, PARKING_LOT + PARKING_SPACES + 1):
                if str(i) not in parked_calls.keys():
                    parked_calls_xml += "<Message Size=\"double\">Empty</Message>"
                else:
                    color = "red" if (i - PARKING_LOT) in pastthreshold else "white" 
                    x = parked_calls[str(i)]
                    parked_calls_xml += "<Message Size=\"double\" Color=\"" + color + "\">" + escape(x["Name"][:12] + (x["Name"][12:] and "..")) + ": " + str(datetime.timedelta(seconds=int(x["Duration"]))) + "</Message>"

            parked_calls_xml += "</YealinkIPPhoneStatus>"

            for ip in aor:
                try:
                    headers = {"Content-Type": "text/xml",
                            "Host": ip,
                            "Referer": FREEPBX_HOST,
                            "Content-Length": str(len(parked_calls_xml)),
                            "Connection": "Keep-Alive"}
                    r = requests.post("https://" + ip + "/servlet?push=xml", headers=headers, data=parked_calls_xml, verify=False)
                    for line in pastthreshold:
                        beep(ip, line)
                except Exception as e:
                    print(e)
                    print(traceback.print_exc())

            parked_calls = dict()

        if (event.name == "ContactList"):
            if event["ViaAddr"] in BLACKLIST_IP:
                return
            aor.add(event["ViaAddr"])

    except Exception as e:
        print(e)
        print(traceback.print_exc())

client.add_event_listener(event_listener, black_list=['VarSet', 'Newexten'])

try:
    i = 0
    first_time = True
    while True:
        client.send_action(SimpleAction('ParkedCalls'))
        if i == 0:
            client.send_action(SimpleAction('PJSIPShowContacts'))
        elif i == 60:
            i = -1
        i += 1
        time.sleep(10)
except (KeyboardInterrupt, SystemExit):
    client.logoff()
