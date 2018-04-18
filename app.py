# import dependencies
import os
import json
import struct
import numpy as np
import datetime as dt
from flask import Flask, request, redirect, url_for, escape, jsonify, make_response
from flask_mongoengine import MongoEngine
from itertools import chain

app = Flask(__name__)
TIME_FORMAT = "%Y-%m-%d_%H:%M:%S"

# check if running in the cloud and set MongoDB settings accordingly
if 'VCAP_SERVICES' in os.environ:
	vcap_services = json.loads(os.environ['VCAP_SERVICES'])
	mongo_credentials = vcap_services['mongodb'][0]['credentials']
	mongo_uri = mongo_credentials['uri']
else:
	mongo_uri = 'mongodb://localhost/db'

app.config['MONGODB_SETTINGS'] = [
	{
		'host': mongo_uri,
		'alias': 'points'
	},
	
]

# bootstrap our app
db = MongoEngine(app)

class DataPoint(db.Document):
	devEUI = db.StringField(required=True)
	deviceType = db.StringField()
	timestamp = db.DateTimeField()
	time = db.StringField()
	gps_lat = db.FloatField()
	gps_lon = db.FloatField()
	gateway_id = db.ListField(db.StringField())
	gateway_rssi = db.ListField(db.FloatField())
	gateway_snr = db.ListField(db.FloatField())
	gateway_esp = db.ListField(db.FloatField())
	tx_pow = db.IntField()
	location = db.ListField(db.IntField())
	experiment_nr = db.ListField(db.IntField())
	#work in a specific mongoDB collection:
	meta = {'db_alias': 'points'}


# set the port dynamically with a default of 3000 for local development
port = int(os.getenv('PORT', '3000'))

# functions for decoding payload
def bitshift (payload,lastbyte):
	return 8*(payload-lastbyte-1)

# our base route which just returns a string
@app.route('/')
def hello_world():
	return "<b>Congratulations! Welcome to Spaghetti v1!</b>"

#output a csv file
#To do: debug (correct nested list import)
@app.route('/csv/<track>')
def print_csv(track):

	#make flattened list for export
	response = chain.from_iterable(make_response(DataPoint.objects(track_ID=track)))

	print(response) 
	cd = 'attachment; filename = export.csv'
	response.headers['Content-Disposition'] = cd
	response.mimetype='text/csv'
	return response

#querying the database and giving back a JSON file
@app.route('/query', methods=['GET'])
def db_query():
	query = request.args
	print('args received')
	print(query)

	track = 0
	start = dt.datetime.now() - dt.timedelta(days=365)
	end = dt.datetime.now()

	#enable for deleting objects. Attention, deletes parts of the database! Should be left disabled.
	if 'delete' in query and 'start' in query and 'end' in query:
		end = dt.datetime.strptime(query['end'], TIME_FORMAT)
		start = dt.datetime.strptime(query['start'], TIME_FORMAT)
		#DataPoint.objects(track_ID=query['delete'],timestamp__lt=end,timestamp__gt=start).delete()
		#return 'objects deleted'
		return 'delete feature disabled for security reasons'

	if 'delpoint' in query:
		#to do: debug this
		DataPoint.objects(timestamp=query['delpoint']).delete()
		return "ok"

	if 'track' in query:
		track = int(query['track'])

	if 'start' in query:
		start = dt.datetime.strptime(query['start'], TIME_FORMAT)
	

	if 'end' in query:
		end = dt.datetime.strptime(query['end'], TIME_FORMAT)

	if 'experiment_nr' in query:
		experiment_nr_q = int(query['experiment_nr'])
		datapoints = DataPoint.objects(experiment_nr = experiment_nr_q,  timestamp__lt=end,timestamp__gt=start).to_json()
		return datapoints
	
	if 'experiment_nr' in query and 'location' in query:
		experiment_nr_q = int(query['experiment_nr'])
		location_q = int(query['location'])
		datapoints = DataPoint.objects(experiment_nr = experiment_nr_q,  timestamp__lt=end,timestamp__gt=start, location_q=location).to_json()
		return datapoints
		
	else:
		datapoints = DataPoint.objects(track_ID=track,timestamp__lt=end,timestamp__gt=start).to_json()
		return datapoints


# Swisscom LPN listener to POST from actility
@app.route('/sc_lpn', methods=['POST'])
def sc_lpn():
	"""
	This methods handle every messages sent by the LORA sensors
	:return:
	"""
	print("Data received from ThingPark...")
	j = []
	try:
		j = request.json
	except:
		print("Unable to read information or json from sensor...")
	
	#print("Args received:")
	#print(args_received)
	print("JSON received:")
	print(j)

	tuino_list = ['78AF580300000485','78AF580300000506']
	direxio_list = ['78AF58060000006D']

	#Parse JSON from ThingPark
	size_payload=10
	payload = j['DevEUI_uplink']['payload_hex']
	payload_int = int(j['DevEUI_uplink']['payload_hex'],16)
	bytes = bytearray.fromhex(payload)
	r_deveui = j['DevEUI_uplink']['DevEUI']
	r_time = j['DevEUI_uplink']['Time']
	#Directive %z not supported in python 2! 
	#Todo: Use Python 3 and remove fixed timezone
	r_timestamp = dt.datetime.strptime(r_time,"%Y-%m-%dT%H:%M:%S.%f+02:00")
	r_sp_fact = j['DevEUI_uplink']['SpFact']
	r_channel = j['DevEUI_uplink']['Channel']
	r_band = j['DevEUI_uplink']['SubBand']

	g_id = []
	g_rssi = []
	g_snr = []
	g_esp = []

	#parse array of multiple gateways
	for index, item in enumerate(j['DevEUI_uplink']['Lrrs']['Lrr']):
		g_id.append(item['Lrrid'])
		g_rssi.append(item['LrrRSSI'])
		g_snr.append(item['LrrSNR'])
		g_esp.append(item['LrrESP'])

	if(r_deveui in tuino_list):
		r_devtype = "tuino-v3"
		#r_lat = struct.unpack('<l', bytes.fromhex(payload[10:18]))[0] /10000000.0
		#r_lon = struct.unpack('<l', bytes.fromhex(payload[18:26]))[0] /10000000.0
		#r_temp = struct.unpack('<i', bytes.fromhex(payload[2:6]))[0] /100.0
		#r_hum = struct.unpack('<i', bytes.fromhex(payload[6:10]))[0] /100.0
		r_lat = ((payload_int & 0x000000000000FFFFFFFF))/10000000.0
		r_lon = ((payload_int & 0x0000FFFFFFFF00000000)>>32)/10000000.0
		r_experiment_nr =((payload_int & 0x00FF0000000000000000)>>64)
		r_location = ((payload_int & 0xFF000000000000000000)>>72)
		
		print('TXpow: ' + str(r_txpow))
		print('SF: '+ str(r_sp_fact))
		print('Lat: ' + str(r_lat))
		print('Lon: ' + str(r_lon))
		print('Experiment Nr: ' + str(experiment_nr))
		if(location==1):
			print('Location: interior')
		else:
			print('Location: exterior')
			

	elif (r_deveui in direxio_list):
		r_devtype = "direxio-v1"
		r_lat = struct.unpack('<f', bytes.fromhex(payload[10:18]))[0]
		r_lon = struct.unpack('<f', bytes.fromhex(payload[20:28]))[0]
		r_sat = 0
		r_hdop = 20
		r_txpow = 0
		
		
		print(r_lat)
		print(r_lon)
	else:
		return "device type not recognised"

	#to check if gps coords are available
	gpfix = 1
	
	#TODO: check if gpscord = 0.0
	
	if gpfix:
		datapoint = DataPoint(devEUI=r_deveui, time= r_time, timestamp = r_timestamp, deviceType = r_devtype, gps_lat=r_lat, gps_lon=r_lon,
			sp_fact=r_sp_fact, channel=r_channel, sub_band=r_band, gateway_id=g_id, gateway_rssi=g_rssi, gateway_snr=g_snr, 
			gateway_esp=g_esp, tx_pow = r_txpow, location=r_location, experiment_nr=r_experiment_nr)
		datapoint.save()
		return 'Datapoint DevEUI %s saved' %(r_deveui)
	else:
		print("no gps coords, point not saved")
		return 'Datapoint DevEUI %s not saved because no gps coords available' %(r_deveui)


# endpoint to return all kittens
@app.route('/db')
def get_data():
	datapoints = DataPoint.objects.to_json()
	return datapoints


def m_to_coord(latlon, meter, deglat):
	R = 40030173
	if latlon == 'lon':
		return (meter/(np.cos(np.radians(deglat))*R))*360.0
	elif latlon == 'lat':
		return (meter/R)*360.0
	else:
		print('return 0')
		return 0

def coord_to_m(latlon, meter, deglat):
	R = 40030173
	if latlon == 'lon':
		return (meter/360.0)*(np.cos(np.radians(deglat))*R)
	elif latlon == 'lat':
		return (meter/360.0)*R
	else:
		return 0
# start the app
if __name__ == '__main__':
	#print(m_to_coord('lat',10000,46.518718))
	#print(m_to_coord('lon',10000,46.518718))
	app.run(host='0.0.0.0', port=port)