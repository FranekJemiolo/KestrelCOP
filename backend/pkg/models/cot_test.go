package models

import (
	"testing"
)

func TestParseCoTJSON_Valid(t *testing.T) {
	raw := `{
		"event": {
			"version": "2.0",
			"uid": "alpha-01",
			"type": "a-f-G-U-C",
			"how": "m-g",
			"time": "2026-09-30T14:35:00.000Z",
			"start": "2026-09-30T14:35:00.000Z",
			"stale": "2026-09-30T14:35:30.000Z",
			"point": {
				"lat": 52.229712,
				"lon": 21.012234,
				"hae": 142.5,
				"ce": 2.1,
				"le": 3.4
			},
			"detail": {
				"contact": {"callsign": "ALPHA-1"}
			}
		}
	}`

	msg, err := ParseCoTJSON([]byte(raw))
	if err != nil {
		t.Fatalf("unexpected error parsing valid cot json: %v", err)
	}

	if msg.Event.UID != "alpha-01" {
		t.Errorf("expected UID 'alpha-01', got %s", msg.Event.UID)
	}
	if msg.Event.Point.Lat != 52.229712 {
		t.Errorf("expected lat 52.229712, got %f", msg.Event.Point.Lat)
	}
	if msg.Event.TacticalAffiliation() != "friendly" {
		t.Errorf("expected tactical affiliation 'friendly', got %s", msg.Event.TacticalAffiliation())
	}
}

func TestParseCoTJSON_InvalidCoords(t *testing.T) {
	raw := `{
		"event": {
			"version": "2.0",
			"uid": "bad-coord-node",
			"type": "a-u-G",
			"time": "2026-09-30T14:35:00Z",
			"point": {
				"lat": 95.5,
				"lon": 21.0
			}
		}
	}`

	_, err := ParseCoTJSON([]byte(raw))
	if err == nil {
		t.Fatal("expected error on out-of-range coordinates, got nil")
	}
}

func TestParseCoTJSON_MissingUID(t *testing.T) {
	raw := `{
		"event": {
			"version": "2.0",
			"uid": "",
			"type": "a-u-G",
			"point": {
				"lat": 52.0,
				"lon": 21.0
			}
		}
	}`

	_, err := ParseCoTJSON([]byte(raw))
	if err == nil {
		t.Fatal("expected error on empty UID, got nil")
	}
}
