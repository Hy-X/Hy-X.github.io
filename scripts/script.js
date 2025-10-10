//const universityOfIllinoisLocation = [40.101952, -88.227161];
const universityOfIllinoisLocation = [35.2088, -97.4457];
let terrainLayer;
let satelliteLayer;

function createMap() {
    //const map = L.map("map").setView([40.0, -89.0], 7);
    const map = L.map("map").setView([35.2, -97.2], 7);

    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        attribution: '© <a href="https://openstreetmap.org">OpenStreetMap</a> contributors'
    }).addTo(map);

    return map;
}

function addUniversityMarker(map) {
    L.marker(universityOfIllinoisLocation)
        .addTo(map)
        //.bindPopup(`University of Illinois<br>Hongyu Xiao`)
        .bindPopup(`University of Oklahoma <br>Dr.Hongyu Xiao`)
        .openPopup();
}

function addTerrainLayer(map) {
    terrainLayer = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/NatGeo_World_Map/MapServer/tile/{z}/{y}/{x}', {
        attribution: 'Map data &copy; <a href="https://www.esri.com">Esri</a>'
    }).addTo(map);
}

function addSatelliteLayer(map) {
    satelliteLayer = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
        attribution: 'Map data &copy; <a href="https://www.esri.com">Esri</a>'
    }).addTo(map);
}

function addEarthquakeCircles(map, earthquakeData) {
    earthquakeData.querySelectorAll("event").forEach(earthquake => {
        const latitude = earthquake.querySelector("latitude").textContent;
        const longitude = earthquake.querySelector("longitude").textContent;
        const magnitude = parseFloat(earthquake.querySelector("magnitude").textContent);
        const Etime = earthquake.querySelector("time").textContent;

        let circleColor = "royalblue"; // Default color
        //let circleRadius = 10000; // Default radius
        let circleRadius = 7000; // Default radius

        if (magnitude > 5) {
            circleColor = "red"; // Change color for magnitude > 5
            //circleRadius = magnitude * 20000; // Adjust radius for magnitude > 5
            circleRadius = magnitude * 15000; // Adjust radius for magnitude > 5
        }

        L.circle([parseFloat(latitude), parseFloat(longitude)], {
            color: circleColor,
            fillColor: circleColor,
            fillOpacity: 0.5,
            radius: circleRadius
        })
        .bindPopup(`Magnitude: ${magnitude}<br>Longitude: ${longitude}<br>Latitude: ${latitude}<br>Time: ${Etime}`)
        .addTo(map);
    });
}


// Toggle terrain layer visibility based on checkbox state
const terrainCheckbox = document.getElementById("terrainCheckbox");
terrainCheckbox.addEventListener("change", () => {
    if (terrainCheckbox.checked) {
        addTerrainLayer(map);
    } else {
        map.removeLayer(terrainLayer);
    }
});

// Toggle satellite layer visibility based on checkbox state
const satelliteCheckbox = document.getElementById("satelliteCheckbox");
satelliteCheckbox.addEventListener("change", () => {
    if (satelliteCheckbox.checked) {
        addSatelliteLayer(map);
    } else {
        map.removeLayer(satelliteLayer);
    }
});

const map = createMap();
addUniversityMarker(map);

const apiUrl = "https://service.iris.edu/fdsnws/event/1/query";
const currentTime = new Date();
const twentyFourHoursAgo = new Date(currentTime.getTime() - 7*24 * 60 * 60 * 1000); // 7*24 hours in milliseconds

const queryParams = new URLSearchParams({
    starttime: twentyFourHoursAgo.toISOString().substr(0, 19), // Format as "YYYY-MM-DDTHH:mm:ss"
    endtime: currentTime.toISOString().substr(0, 19),
    //minmagnitude: 0.5,
    minmagnitude: 0.1
    // Add more query parameters as needed
});

const requestUrl = `${apiUrl}?${queryParams}`;

fetch(requestUrl)
    .then(response => response.text())
    .then(xmlData => {
        const parser = new DOMParser();
        const xmlDoc = parser.parseFromString(xmlData, "text/xml");
        addEarthquakeCircles(map, xmlDoc);
    })
    .catch(error => {
        console.error("Error fetching earthquake data:", error);
    });


AOS.init();
