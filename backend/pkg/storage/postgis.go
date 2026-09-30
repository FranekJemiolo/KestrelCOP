package storage

import (
	"context"
	"database/sql"
	"encoding/json"
	"fmt"
	"log"
	"sync"
	"time"

	_ "github.com/lib/pq"
	"github.com/FranekJemiolo/KestrelCOP/backend/pkg/models"
)

// Repository manages persistence of tactical Cursor-on-Target telemetry.
type Repository struct {
	db          *sql.DB
	memoryCache map[string]*models.CoTEvent
	mu          sync.RWMutex
	connected   bool
}

// NewRepository initializes a connection to PostgreSQL/PostGIS.
func NewRepository(dsn string) (*Repository, error) {
	repo := &Repository{
		memoryCache: make(map[string]*models.CoTEvent),
	}

	if dsn == "" {
		log.Println("[STORAGE] No PostgreSQL DSN configured. Operating in in-memory storage mode.")
		return repo, nil
	}

	db, err := sql.Open("postgres", dsn)
	if err != nil {
		log.Printf("[STORAGE] Failed to open DB connection: %v. Using in-memory fallback.", err)
		return repo, nil
	}

	db.SetMaxOpenConns(25)
	db.SetMaxIdleConns(10)
	db.SetConnMaxLifetime(5 * time.Minute)

	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()

	if err := db.PingContext(ctx); err != nil {
		log.Printf("[STORAGE] PostgreSQL ping failed: %v. Running in-memory cache until DB reconnects.", err)
	} else {
		repo.db = db
		repo.connected = true
		log.Println("[STORAGE] Connected to PostgreSQL/PostGIS successfully.")
	}

	return repo, nil
}

// SaveCoTEvent records a validated CoT event to PostGIS and updates latest entity memory cache.
func (r *Repository) SaveCoTEvent(ctx context.Context, msg *models.CoTMessage) error {
	evt := &msg.Event

	// Always update local memory cache for immediate sub-millisecond API response
	r.mu.Lock()
	r.memoryCache[evt.UID] = evt
	r.mu.Unlock()

	if !r.connected || r.db == nil {
		return nil
	}

	evtTime, _ := evt.ParsedTime()
	staleTime, _ := evt.ParsedStale()
	startTime := evtTime

	detailJSON, err := json.Marshal(evt.Detail)
	if err != nil {
		detailJSON = []byte("{}")
	}

	query := `
		INSERT INTO cot_events (
			uid, cot_type, how, event_time, start_time, stale_time,
			latitude, longitude, hae, ce, le, detail
		) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
	`

	_, err = r.db.ExecContext(
		ctx,
		query,
		evt.UID,
		evt.Type,
		evt.How,
		evtTime,
		startTime,
		staleTime,
		evt.Point.Lat,
		evt.Point.Lon,
		evt.Point.Hae,
		evt.Point.Ce,
		evt.Point.Le,
		string(detailJSON),
	)

	if err != nil {
		return fmt.Errorf("failed inserting cot record to postgis: %w", err)
	}

	return nil
}

// GetActiveEntities returns the freshest state of all tracked units.
func (r *Repository) GetActiveEntities() []*models.CoTEvent {
	r.mu.RLock()
	defer r.mu.RUnlock()

	entities := make([]*models.CoTEvent, 0, len(r.memoryCache))
	for _, evt := range r.memoryCache {
		entities = append(entities, evt)
	}
	return entities
}

// Close closes the underlying database pool.
func (r *Repository) Close() error {
	r.mu.Lock()
	defer r.mu.Unlock()

	if r.db != nil {
		log.Println("[STORAGE] Closing PostgreSQL/PostGIS connection pool...")
		err := r.db.Close()
		r.connected = false
		if err != nil {
			return fmt.Errorf("error closing PostGIS connection pool: %w", err)
		}
		log.Println("[STORAGE] PostGIS connection pool closed cleanly.")
		return nil
	}
	return nil
}
