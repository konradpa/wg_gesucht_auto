// ImmoScout token helper. Its stdout is a private JSON protocol for the Python
// client; diagnostics go to stderr without token values or response bodies.
package main

import (
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"net/url"
	"os"
	"regexp"
	"strings"
	"time"

	http "github.com/bogdanfinn/fhttp"
	tlsclient "github.com/bogdanfinn/tls-client"
	"github.com/bogdanfinn/tls-client/profiles"
	"immoscoutwaf/internal/aws"
)

const immoHost = "www.immobilienscout24.de"
const defaultUA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36"

var sdkScript = regexp.MustCompile(`(?i)<script\b[^>]*\bsrc\s*=\s*["'](https://[^"']+/challenge\.js(?:\?[^"']*)?)["']`)

func main() {
	searchURL := flag.String("url", "", "ImmoScout /Suche/... URL to validate")
	ua := flag.String("user-agent", defaultUA, "User-Agent shared with the search client")
	bootstrapStdin := flag.Bool("bootstrap-stdin", false, "Read the rejected search HTML from stdin")
	flag.Parse()
	// Bound upstream proof-of-work loops as well as network calls.
	deadline := time.AfterFunc(90*time.Second, func() { fail("token helper timed out") })
	defer deadline.Stop()
	var bootstrap []byte
	if *bootstrapStdin {
		var err error
		bootstrap, err = io.ReadAll(io.LimitReader(os.Stdin, 4<<20))
		if err != nil || len(bootstrap) == 0 {
			fail("cannot read search bootstrap from stdin")
		}
	}
	token, err := acquire(*searchURL, *ua, bootstrap)
	if err != nil {
		fail(err.Error())
	}
	if err := json.NewEncoder(os.Stdout).Encode(map[string]string{
		"token": token, "user_agent": *ua,
	}); err != nil {
		fail("cannot return helper response")
	}
}

func fail(message string) {
	fmt.Fprintln(os.Stderr, message)
	os.Exit(1)
}

func acquire(searchURL, ua string, bootstrap []byte) (string, error) {
	u, err := url.Parse(searchURL)
	if err != nil || u.Scheme != "https" || u.Host != immoHost || u.User != nil ||
		!strings.HasPrefix(u.Path, "/Suche/") || u.Fragment != "" {
		return "", errors.New("expected an ImmoScout HTTPS search URL")
	}
	client, err := tlsclient.NewHttpClient(tlsclient.NewNoopLogger(),
		tlsclient.WithTimeoutSeconds(20),
		tlsclient.WithClientProfile(profiles.Chrome_133),
		tlsclient.WithNotFollowRedirects(),
		tlsclient.WithCookieJar(tlsclient.NewCookieJar()),
	)
	if err != nil {
		return "", errors.New("cannot initialize token helper HTTP client")
	}
	defer client.CloseIdleConnections()
	body := bootstrap
	if len(body) == 0 {
		response, fetchedBody, err := get(client, searchURL, ua, "text/html")
		if err != nil {
			return "", err
		}
		if response.StatusCode != 200 && response.StatusCode != 401 && response.StatusCode != 403 && response.StatusCode != 202 {
			return "", fmt.Errorf("search bootstrap returned HTTP %d", response.StatusCode)
		}
		body = fetchedBody
	}
	matches := sdkScript.FindAllSubmatch(body, -1)
	var prefix string
	for _, match := range matches {
		script, err := url.Parse(string(match[1]))
		if err != nil || script.Scheme != "https" || script.User != nil || script.Port() != "" ||
			!strings.HasSuffix(script.Hostname(), ".edge.sdk.awswaf.com") {
			continue
		}
		prefix = script.Host + strings.TrimSuffix(script.Path, "/challenge.js")
		break
	}
	if prefix == "" {
		return "", errors.New("ImmoScout response contains no supported AWS SDK script")
	}
	// SDK-integrated pages do not supply inline gokuProps. Their token provider
	// accepts this SDK flow; MP support is included from upstream PR #11.
	waf, err := aws.NewAwsWaf(prefix, immoHost, ua, aws.GokuProps{}, "")
	if err != nil {
		return "", errors.New("cannot initialize AWS token flow")
	}
	defer waf.Session.CloseIdleConnections()
	token, err := waf.Run()
	if err != nil {
		return "", errors.New("AWS token acquisition failed")
	}
	if token == "" {
		return "", errors.New("AWS token provider returned an empty token")
	}
	waf.Session.SetCookies(u, []*http.Cookie{{
		Name: "aws-waf-token", Value: token, Domain: immoHost, Path: "/", Secure: true,
	}})
	response, body, err := get(waf.Session, searchURL, ua, "application/json")
	if err != nil {
		return "", err
	}
	if response.StatusCode != 200 || !strings.Contains(strings.ToLower(response.Header.Get("Content-Type")), "application/json") {
		return "", fmt.Errorf("new token rejected by search (HTTP %d)", response.StatusCode)
	}
	var document struct {
		Model struct {
			Result struct {
				Paging *json.RawMessage `json:"paging"`
			} `json:"resultlist.resultlist"`
		} `json:"searchResponseModel"`
	}
	if json.Unmarshal(body, &document) != nil || document.Model.Result.Paging == nil {
		return "", errors.New("new token did not produce valid search JSON")
	}
	return token, nil
}

func get(client tlsclient.HttpClient, target, ua, accept string) (*http.Response, []byte, error) {
	request, err := http.NewRequest(http.MethodGet, target, nil)
	if err != nil {
		return nil, nil, errors.New("cannot construct token helper request")
	}
	request.Header = http.Header{"accept": {accept}, "user-agent": {ua}}
	response, err := client.Do(request)
	if err != nil {
		return nil, nil, errors.New("token helper network request failed")
	}
	defer response.Body.Close()
	body, err := io.ReadAll(io.LimitReader(response.Body, 4<<20))
	if err != nil {
		return nil, nil, errors.New("cannot read token helper response")
	}
	return response, body, nil
}
