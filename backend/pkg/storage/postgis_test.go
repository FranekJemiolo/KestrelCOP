package storage

import (
	"context"
	"testing"
	"time"

	"github.com/FranekJemiolo/KestrelCOP/backend/pkg/models"
)

func TestRepository_InMemoryAndClose(t *testing.T) {
	repo, err := NewRepository("")
	if err != nil {
		t.Fatalf("failed initializing repository in memory mode: %v", err)
	}

	msg := &models.CoTMessage{
		Event: models.CoTEvent{
			Version: "2.0",
			UID:     "test-node-1",
			Type:    "a-f-G-U-C",
			How:     "m-g",
			Time:    time.Now().UTC().Format(time.RFC3339),
			Start:   time.Now().UTC().Format(time.RFC3339),
			Stale:   time.Now().UTC().Add(time.Minute).Format(time.RFC3339),
			Point: models.CoTPoint{
				Lat: 52.23,
				Lon: 21.01,
				Hae: 110.0,
				Ce:  5.0,
				Le:  5.0,
			},
		},
	}

	ctx := context.Background()
	if err := repo.SaveCoTEvent(ctx, msg); err != nil {
		t.Fatalf("failed saving CoT event: %v", err)
	}

	entities := repo.GetActiveEntities()
	if len(entities) != 1 {
		t.Fatalf("expected 1 entity in cache, got %d", len(entities))
	}
	if entities[0].UID != "test-node-1" {
		t.Fatalf("expected UID 'test-node-1', got %s", entities[0].UID)
	}

	if err := repo.Close(); err != nil {
		t.Fatalf("expected clean close of repository, got %v", err)
	}
}
