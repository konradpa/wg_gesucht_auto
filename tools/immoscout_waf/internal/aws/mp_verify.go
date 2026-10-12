// AWS WAF NetworkBandwidth (mp_verify) challenge solver.
//
// This challenge type was identified by xKiian as "mp_verify" but never
// implemented. Reverse-engineering by Felixoid (pytr-org/pytr#320) showed it's
// a "bandwidth challenge": the client returns a base64-encoded buffer of zeros
// sized by difficulty, submitted via multipart form to /mp_verify.
//
// Algorithm port from https://github.com/pytr-org/pytr/blob/master/pytr/awswaf/verify.py
// (MIT licensed, also vendored from xKiian/awswaf upstream).
package aws

import (
	"bytes"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"log"
	"mime/multipart"
	"strings"

	http "github.com/bogdanfinn/fhttp"
)

// MpVerifyType is the SHA-256 ID Amazon assigns to the NetworkBandwidth challenge.
// In the obfuscated challenge.js JWT, this is decoded as challenge_type=NetworkBandwidth.
const MpVerifyType = "ha9faaffd31b4d5ede2a2e19d2d7fd525f66fee61911511960dcbb52d3c48ce25"

// Default solution buffer sizes per difficulty level.
// Matches pytr's _DEFAULT_BANDWIDTH_SIZES — extracted from the challenge.js
// switch(difficulty) block: 0x1→1KB, 0x2→10KB, 0x3→100KB, 0x4→1MB, 0x5→10MB.
var defaultBandwidthSizes = map[int]int{
	1: 0x400,          // 1 KiB
	2: 0xA * 0x400,    // 10 KiB
	3: 0x64 * 0x400,   // 100 KiB
	4: 0x100000,       // 1 MiB
	5: 0xA * 0x100000, // 10 MiB
}

// NetworkBandwidth returns the solution string for the mp_verify challenge type:
// base64-encoded buffer of zero bytes sized by the difficulty parameter.
//
// challengeInput and checksum are accepted for API symmetry with HashPoW /
// ComputeScryptNonce but are not used — this challenge does not depend on them.
func NetworkBandwidth(challengeInput, checksum string, difficulty int) (string, error) {
	size, ok := defaultBandwidthSizes[difficulty]
	if !ok {
		return "", fmt.Errorf("unsupported bandwidth difficulty: %d", difficulty)
	}
	return base64.StdEncoding.EncodeToString(make([]byte, size)), nil
}

// VerifyMultipart submits the payload to /mp_verify as multipart form data.
// solution_data carries the base64 zero buffer (the actual "solution"),
// solution_metadata carries the rest of the payload as JSON with solution=null.
//
// AWS WAF requires this exact submission shape for the NetworkBandwidth challenge —
// posting as JSON to /verify (the legacy endpoint) is silently accepted by the
// server but the resulting token may be rejected on follow-up requests.
func (a *Waf) VerifyMultipart(payload *Verify) (string, error) {
	url := fmt.Sprintf("https://%s/mp_verify", a.Host)

	// Pop the solution out — solution_data carries it; metadata gets null.
	solution := payload.Solution
	payload.Solution = ""
	metadata, err := json.Marshal(struct {
		*Verify
		Solution *string `json:"solution"`
	}{Verify: payload, Solution: nil})
	if err != nil {
		return "", fmt.Errorf("marshal metadata: %w", err)
	}

	var body bytes.Buffer
	mw := multipart.NewWriter(&body)
	if err := mw.WriteField("solution_data", solution); err != nil {
		return "", fmt.Errorf("write solution_data: %w", err)
	}
	if err := mw.WriteField("solution_metadata", string(metadata)); err != nil {
		return "", fmt.Errorf("write solution_metadata: %w", err)
	}
	if err := mw.Close(); err != nil {
		return "", fmt.Errorf("close multipart: %w", err)
	}

	req, err := http.NewRequest(http.MethodPost, url, strings.NewReader(body.String()))
	if err != nil {
		log.Println(err)
		return "", err
	}
	req.Header = http.Header{
		"accept":             {"*/*"},
		"accept-encoding":    {"gzip, deflate, br, zstd"},
		"accept-language":    {"en-US,en;q=0.9"},
		"connection":         {"keep-alive"},
		"content-type":       {mw.FormDataContentType()},
		"priority":           {"u=1, i"},
		"sec-ch-ua-mobile":   {"?0"},
		"sec-ch-ua-platform": {`"Windows"`},
		"sec-fetch-dest":     {"empty"},
		"sec-fetch-mode":     {"cors"},
		"sec-fetch-site":     {"cross-site"},
		"user-agent":         {a.UserAgent},
		http.HeaderOrderKey: {
			"accept", "accept-encoding", "accept-language", "connection",
			"content-length", "content-type", "priority",
			"sec-ch-ua-mobile", "sec-ch-ua-platform",
			"sec-fetch-dest", "sec-fetch-mode", "sec-fetch-site", "user-agent",
		},
	}

	resp, err := a.Session.Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		return "", fmt.Errorf("token verification returned HTTP %d", resp.StatusCode)
	}

	var out VerifyRes
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return "", err
	}
	if out.Token == "" {
		return "", fmt.Errorf("token verification returned an empty token")
	}
	return out.Token, nil
}
