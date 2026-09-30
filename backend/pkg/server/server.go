package server

import (
	"encoding/json"
	"net/http"
	"time"

	"github.com/FranekJemiolo/KestrelCOP/backend/pkg/storage"
	"github.com/FranekJemiolo/KestrelCOP/backend/pkg/ws"
)

// Server coordinates HTTP and WebSocket routes.
type Server struct {
	mux     *http.ServeMux
	hub     *ws.Hub
	storage *storage.Repository
}

// NewServer initializes HTTP handlers.
func NewServer(hub *ws.Hub, repo *storage.Repository) *Server {
	s := &Server{
		mux:     http.NewServeMux(),
		hub:     hub,
		storage: repo,
	}

	s.routes()
	return s
}

func (s *Server) routes() {
	s.mux.HandleFunc("/healthz", s.handleHealthz)
	s.mux.HandleFunc("/ws", s.hub.ServeWs)
	s.mux.HandleFunc("/api/v1/entities", s.handleEntities)
}

func (s *Server) handleHealthz(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]interface{}{
		"status":          "operational",
		"timestamp":       time.Now().UTC().Format(time.RFC3339),
		"service":         "kestrel-collector",
		"version":         "0.1.0",
		"active_ws_peers": s.hub.ClientCount(),
	})
}

func (s *Server) handleEntities(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Access-Control-Allow-Origin", "*")

	entities := s.storage.GetActiveEntities()
	json.NewEncoder(w).Encode(map[string]interface{}{
		"count":    len(entities),
		"entities": entities,
	})
}

// Handler returns the HTTP handler with CORS support.
func (s *Server) Handler() http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Access-Control-Allow-Origin", "*")
		w.Header().Set("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
		w.Header().Set("Access-Control-Allow-Headers", "Content-Type, Authorization")

		if r.Method == http.MethodOptions {
			w.WriteHeader(http.StatusOK)
			return
		}

		s.mux.ServeHTTP(w, r)
	})
}
