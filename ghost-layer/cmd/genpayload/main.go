package main

import (
	"encoding/json"
	"fmt"
	"math"
	"strings"
)

type FaceState struct {
	Center   int       `json:"center"`
	Edges    []int     `json:"edges"`
	Corners  []float64 `json:"corners"`
	Rotation int       `json:"rotation"`
}

func djb2(s string) uint32 {
	h := uint32(5381)
	for _, c := range []byte(s) {
		h = ((h << 5) + h) ^ uint32(c)
	}
	return h
}

func computeCenter(f *FaceState) int {
	rot := f.Rotation % 4
	var wSum, wTotal float64
	for i := 0; i < 4; i++ {
		cIdx := (i + rot) % 4
		wSum += float64(f.Edges[i]) * f.Corners[cIdx]
		wTotal += f.Corners[cIdx]
	}
	if wTotal == 0 {
		return 0
	}
	return int(math.Round(wSum / wTotal))
}

func main() {
	order := []string{"px", "nx", "py", "ny", "pz", "nz"}

	// Uniform corners=1.0 rotation=0 → center = round(mean(edges))
	// Set all edges to the target center value
	targets := map[string]int{
		"px": 50,  // bounds [0,100]
		"nx": 5,   // bounds [0,10]
		"py": 420, // bounds [100,5000]
		"ny": 25,  // bounds [0,50]
		"pz": 10,  // bounds [0,20]
		"nz": 200, // bounds [0,500]
	}

	faces := map[string]*FaceState{}
	for _, k := range order {
		c := targets[k]
		faces[k] = &FaceState{
			Center:   c,
			Edges:    []int{c, c, c, c},
			Corners:  []float64{1.0, 1.0, 1.0, 1.0},
			Rotation: 0,
		}
	}

	// Verify computed centers match submitted centers (server will reject mismatches)
	for _, k := range order {
		f := faces[k]
		got := computeCenter(f)
		if got != f.Center {
			fmt.Printf("MISMATCH face %s: submitted=%d computed=%d\n", k, f.Center, got)
			return
		}
	}

	// Build state string exactly as server does
	var parts []string
	for _, key := range order {
		f := faces[key]
		parts = append(parts, fmt.Sprintf("%sc:%d", key, f.Center))
		for i, e := range f.Edges {
			parts = append(parts, fmt.Sprintf("%se%d:%d", key, i, e))
		}
		for i, c := range f.Corners {
			parts = append(parts, fmt.Sprintf("%sk%d:%.1f", key, i, c))
		}
	}
	stateStr := strings.Join(parts, "|")
	hash := fmt.Sprintf("CUBE-%08X", djb2(stateStr))

	payload := map[string]interface{}{
		"hash":  hash,
		"faces": faces,
	}
	b, _ := json.Marshal(payload)
	fmt.Println(string(b))
}
