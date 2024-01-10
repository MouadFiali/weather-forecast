const express = require('express');
const cors = require('cors');
const { connectDB, getDB } = require('./database');
const KafkaConfig = require('./kafka');
const getCityCoords = require('./geoApi');
const config = require('./config');

const app = express();
const host = config.server.host;
const port = config.server.port; // Use a different port from your React app

const responseMap = new Map(); // Map to store response objects

//// Functions
const processCityData = (message) => {
  const data = JSON.parse(message);
  const responses = responseMap.get(data.city);
  if (responses) {
    responses.forEach(res => res.json(data));
    responseMap.delete(data.city); // Remove the responses from the map
  }
};

// Instanciate and connect kafka consumer & producer
const kafkaConfig = new KafkaConfig();
kafkaConfig.connectProducer();
kafkaConfig.connectSubscribeAndRunConsumer("response",processCityData);

// Handle CORS issues
app.use(cors());

// Middleware to parse JSON bodies
app.use(express.json());

// Connect to MongoDB
connectDB().then(() => {
  console.log('Connected to MongoDB');
}).catch(error => {
  console.error('Database connection failed', error);
  process.exit(1);
});

// Test route
app.get('/', (req, res) => {
  res.send('Hello from the backend!');
});

// Route to handle city search
app.get('/search', async (req, res) => {
  try {
    const city = req.query.city; // Extract city from query parameters
    console.log('City received:', city);
    const db = getDB();

    // Query the database for the city data
    const cityData = await db.collection('cities').findOne({ city: city });
      if (cityData) {
        res.json(cityData);
      } else {
        // Data not found in the database, send request to Kafka
        const coords = await getCityCoords(city);
        console.log(coords);
        const message = {
          city: city,
          lat: coords.latitude,
          lon: coords.longitude
        };
        await kafkaConfig.produce("requests", [{ value: JSON.stringify(message) }]);
        // res.status(404).send('City data requested from producer');
        // consumeCityData(city, res);
        if (!responseMap.has(city)) {
          responseMap.set(city, []);
        }
        responseMap.get(city).push(res);
      }
    } catch (error) {
      console.log(error)
      res.status(500).send('Error accessing database');
    }
});

process.on('SIGINT', async () => {
  console.log('Shutting down...');
  try {
    await kafkaConfig.producer.disconnect();
    await kafkaConfig.consumer.disconnect();
    console.log('Kafka producer and consumer disconnected');
    process.exit(0);
  } catch (error) {
    console.error('Error during shutdown:', error);
    process.exit(1);
  }
});

app.listen(port, host, () => {
  console.log(`Server listening at http://${host}:${port}`);
});


