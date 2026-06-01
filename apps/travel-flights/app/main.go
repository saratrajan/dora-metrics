package main

import (
	"encoding/json"
	"log"
	"net/http"
	"os"
)

var version = "dev" // overridden at build time via -ldflags "-X main.version=x.y.z"

type Flight struct {
	ID          string `json:"id"`
	Origin      string `json:"origin"`
	Destination string `json:"destination"`
	Airline     string `json:"airline"`
	Departure   string `json:"departure"`
	Price       int    `json:"price_usd"`
}

var flights = []Flight{
	{"FL001", "JFK", "LAX", "SkyWings", "2025-06-01T08:00:00Z", 320},
	{"FL002", "SFO", "ORD", "PacificAir", "2025-06-01T10:30:00Z", 210},
	{"FL003", "MIA", "SEA", "SunJet", "2025-06-01T14:00:00Z", 475},
	{"FL004", "BOS", "DEN", "EastWing", "2025-06-01T07:15:00Z", 185},
}

func main() {
	port := os.Getenv("PORT")
	if port == "" {
		port = "9080"
	}

	mux := http.NewServeMux()
	mux.HandleFunc("/", handleRoot)
	mux.HandleFunc("/flights", handleFlights)
	mux.HandleFunc("/healthz", handleHealth)
	mux.HandleFunc("/status", handleStatus)

	log.Printf("travel-flights %s listening on :%s", version, port)
	if err := http.ListenAndServe(":"+port, mux); err != nil {
		log.Fatal(err)
	}
}

func handleRoot(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]interface{}{
		"service": "travel-flights",
		"version": version,
		"routes":  len(flights),
	})
}

func handleFlights(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(flights)
}

func handleHealth(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	json.NewEncoder(w).Encode(map[string]string{"status": "ok"})
}

func handleStatus(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]interface{}{
		"service": "travel-flights",
		"version": version,
		"status":  "running",
		"routes":  len(flights),
	})
}
