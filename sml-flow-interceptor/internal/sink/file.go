package sink

import (
	"encoding/json"
	"os"
	"sync"

	"sml-flow-interceptor/internal/events"
)

// File is an append-only NDJSON sink. Writes are unbuffered so a crash loses
// at most the current syscall's worth of data; at filtered mempool + ticker
// rates the syscall cost is negligible.
type File struct {
	mu  sync.Mutex
	f   *os.File
	enc *json.Encoder
}

func OpenFile(path string) (*File, error) {
	f, err := os.OpenFile(path, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0644)
	if err != nil {
		return nil, err
	}
	return &File{f: f, enc: json.NewEncoder(f)}, nil
}

func (s *File) Write(e events.Event) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.enc.Encode(e)
}

func (s *File) Close() error {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.f.Close()
}
