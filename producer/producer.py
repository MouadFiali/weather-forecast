from kafka import KafkaProducer, KafkaConsumer
from kafka.errors import KafkaError
from datetime import datetime
import requests
import os
from dotenv import load_dotenv
from database import Database
import json
import threading

load_dotenv()

def json_serializer(data):
    return json.dumps(data).encode("utf-8")

def json_deserializer(data):
    return json.loads(data.decode("utf-8"))

def send_to_kafka(city, wind_data):
    try:
        print("Data filtered, sending to Kafka for " + city + "...")
        producer.send('weather', key=city.encode(), value=wind_data)
        producer.flush()
    except KafkaError as e:
        print("Failed to send data to Kafka: ")
        print(e)

def filter_data(city, weather_data):
    print("Filtering data for city: " + city)
    current = weather_data['current_weather']
    forecast = weather_data['forecast']
    wind_data = {
        "timestamp": datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'),
        "city": city,
        "current": {
            "wind": current['wind'],
            "temp": current['main']['temp'],
            "pressure": current['main']['pressure'] * 100, # Convert hPa to Pa for air density calculation in consumer
            "humidity": current['main']['humidity'] / 100, # Convert % to decimal for air density calculation in consumer
            "date": datetime.utcfromtimestamp(current['dt']).strftime('%Y-%m-%d %H:%M:%S').split(' ')[0]
        },
        "forecast": []
    }
    for forecast_data in forecast['list']:
        data = {
            "wind": forecast_data['wind'],
            "temp": forecast_data['main']['temp'],
            "pressure": forecast_data['main']['pressure'] * 100, # Convert hPa to Pa for air density calculation in consumer
            "humidity": forecast_data['main']['humidity'] / 100, # Convert % to decimal for air density calculation in consumer
            "dt": datetime.utcfromtimestamp(forecast_data['dt']).strftime('%Y-%m-%d %H:%M:%S')
        }
        wind_data['forecast'].append(data)
    return wind_data

def get_weather_data(lat, lon):
    # TODO: Handle reaching API limit
    print("Getting weather data for city: " + lat + ", " + lon)
    api_key = os.getenv('WEATHER_API_KEY')
    current_weather_url = os.getenv('API_URL') + "/weather"
    forecast_url = os.getenv('API_URL') + "/forecast"
    params = {
        "lat": lat,
        "lon": lon,
        "appid": api_key,
        "units": "metric"
    }

    current_weather_response = requests.get(current_weather_url, params=params)
    forecast_response = requests.get(forecast_url, params=params)

    if current_weather_response.status_code != 200 or forecast_response.status_code != 200:
        print("Failed to get weather data for city: " + lat + ", " + lon)
        return
    
    current_weather_data = current_weather_response.json()
    forecast_data = forecast_response.json()

    return {
        "current_weather": current_weather_data,
        "forecast": forecast_data
    }

def check_pending_cities(city):
    # To make sure the producer is stateless, we do the check in the database
    database = Database()
    if database.find_one({"pending_cities": city}):
        return True
    # If the city is not in the database, add it (It's being processed)
    database.insert({"pending_cities": city})
    return False

def remove_pending_city(city):
    database = Database()
    if database.find_one({"pending_cities": city}):
        database.delete({"pending_cities": city})
    database.close()

def handle_request(message):
    print("****************************************************")
    print("Received request for city: " + message.value['city'])
    data = message.value
    city = data['city']
    lat = data['lat']
    lon = data['lon']
    if check_pending_cities(city):
        print("City already being processed: " + city)
        return
    weather_data = get_weather_data(lat, lon)
    filtered_data = filter_data(city, weather_data)
    send_to_kafka(city, filtered_data)
    remove_pending_city(city)
    print("Data sent to kafka and removed from pending list: " + city)

if __name__ == "__main__":
    try:
        bootstrap_servers = [os.getenv('KAFKA_BOOTSTRAP_SERVERS')]
        print("Starting producer on " + bootstrap_servers[0] + "...")
        producer = KafkaProducer(bootstrap_servers=bootstrap_servers, value_serializer=json_serializer)
        consumer = KafkaConsumer('requests', bootstrap_servers=bootstrap_servers, value_deserializer=json_deserializer)
        print("Producer started on broker: " + bootstrap_servers[0])
        print("A consumer has been started for backend communication, broker: " + bootstrap_servers[0])
        for message in consumer:
            threading.Thread(target=handle_request, args=(message,)).start()
    except KafkaError as e:
        print("Failed to connect to Kafka: ")
        print(e)