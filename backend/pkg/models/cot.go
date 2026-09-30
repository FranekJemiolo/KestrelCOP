package models

import (
	"encoding/json"
	"errors"
	"fmt"
	"strings"
	"time"
)

var (
	ErrInvalidUID      = errors.New("cot event missing mandatory uid")
	ErrInvalidType     = errors.New("cot event missing mandatory tactical type")
	ErrInvalidCoords   = errors.New("cot point coordinates out of valid WGS84 range (-90..90 lat, -180..180 lon)")
	ErrInvalidTime     = errors.New("cot event has invalid timestamp format")
	ErrEmptyPayload    = errors.New("empty cot message payload")
)

// CoTMessage represents the root Cursor-on-Target 2.0 JSON envelope.
type CoTMessage struct {
	Event CoTEvent `json:"event"`
}

// CoTPoint holds the geospatial fix attributes.
type CoTPoint struct {
	Lat float64 `json:"lat"`
	Lon float64 `json:"lon"`
	Hae float64 `json:"hae"`
	Ce  float64 `json:"ce"`
	Le  float64 `json:"le"`
}

// CoTEvent defines the standardized Cursor-on-Target event schema.
type CoTEvent struct {
	Version string                 `json:"version"`
	UID     string                 `json:"uid"`
	Type    string                 `json:"type"`
	How     string                 `json:"how"`
	Time    string                 `json:"time"`
	Start   string                 `json:"start"`
	Stale   string                 `json:"stale"`
	Point   CoTPoint               `json:"point"`
	Detail  map[string]interface{} `json:"detail,omitempty"`
}

// ParseCoTJSON parses and validates raw JSON bytes into a CoTMessage.
func ParseCoTJSON(data []byte) (*CoTMessage, error) {
	if len(data) == 0 {
		return nil, ErrEmptyPayload
	}

	var msg CoTMessage
	if err := json.Unmarshal(data, &msg); err != nil {
		return nil, fmt.Errorf("malformed cot json: %w", err)
	}

	if err := msg.Validate(); err != nil {
		return nil, err
	}

	return &msg, nil
}

// Validate verifies mandatory fields and geospatial bounds.
func (m *CoTMessage) Validate() error {
	evt := &m.Event
	if strings.TrimSpace(evt.UID) == "" {
		return ErrInvalidUID
	}
	if strings.TrimSpace(evt.Type) == "" {
		return ErrInvalidType
	}
	if evt.Point.Lat < -90.0 || evt.Point.Lat > 90.0 || evt.Point.Lon < -180.0 || evt.Point.Lon > 180.0 {
		return ErrInvalidCoords
	}

	if _, err := evt.ParsedTime(); err != nil {
		return fmt.Errorf("%w: %v", ErrInvalidTime, err)
	}

	return nil
}

// ParsedTime returns the observation time as a UTC time.Time.
func (e *CoTEvent) ParsedTime() (time.Time, error) {
	return parseISO(e.Time)
}

// ParsedStale returns the stale expiration timestamp as a UTC time.Time.
func (e *CoTEvent) ParsedStale() (time.Time, error) {
	return parseISO(e.Stale)
}

// IsStale returns true if the event stale timestamp has passed.
func (e *CoTEvent) IsStale() bool {
	staleTime, err := e.ParsedStale()
	if err != nil {
		return false
	}
	return time.Now().UTC().After(staleTime)
}

// TacticalAffiliation determines entity MIL-STD-2525 category (friendly, hostile, neutral, unknown).
func (e *CoTEvent) TacticalAffiliation() string {
	parts := strings.Split(e.Type, "-")
	if len(parts) >= 2 && parts[0] == "a" {
		switch parts[1] {
		case "f":
			return "friendly"
		case "h":
			return "hostile"
		case "n":
			return "neutral"
		case "u":
			return "unknown"
		}
	}
	if strings.HasPrefix(e.Type, "b-m") {
		return "biometric"
	}
	return "unknown"
}

func parseISO(s string) (time.Time, error) {
	if s == "" {
		return time.Now().UTC(), nil
	}
	// Try RFC3339Nano then RFC3339
	t, err := time.Parse(time.RFC3339Nano, s)
	if err == nil {
		return t.UTC(), nil
	}
	t, err = time.Parse(time.RFC3339, s)
	if err == nil {
		return t.UTC(), nil
	}
	return time.Time{}, err
}
