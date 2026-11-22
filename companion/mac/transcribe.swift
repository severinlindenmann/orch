// orch Companion, step 6 (ORCH-1268): send a finished recording to our transcription service and keep the
// transcript. Design: ORCH-1268 transcript-design.md. API: contracts/transcription-api.md (encrypted jobs).
//
//   recordings/<id>/transcript.json   {v, id, state: waiting|done|failed, problem?, next_try?, started, minutes,
//                                      app, language, lines: [{start, end, who: me|others, text}]}  (0600)
//   recordings/<id>/journal.json      the sender's progress: service, pieces, open jobs, tries      (0600)
//   recordings/<id>/piece-<track>-<n>.json   one finished piece's lines (text), until the transcript is written
//
// Each track is cut into pieces of at most 30 minutes on the recording's own timeline, each piece is sent as a WAV
// inside an OPF1 blob encrypted with a new job key (kept in the Keychain while its job is open, so a restart goes
// on with the same job), one job at a time. The audio is never written to disk unencrypted. The recording itself
// is never deleted here.

import CryptoKit
import Foundation

let pieceSecondsDefault = 1800.0
let backoff: [Double] = [60, 120, 300, 600, 1800, 3600]
let maxPieceFails = 3
let maxResultBytes = 20 << 20
let maxLines = 20000

// MARK: - pure pieces (checked by --selftest)

func b64url(_ d: Data) -> String {
    d.base64EncodedString().replacingOccurrences(of: "+", with: "-").replacingOccurrences(of: "/", with: "_")
        .replacingOccurrences(of: "=", with: "")
}

func unb64url(_ s: String) -> Data? {
    var t = s.replacingOccurrences(of: "-", with: "+").replacingOccurrences(of: "_", with: "/")
    while t.count % 4 != 0 { t += "=" }
    return Data(base64Encoded: t)
}

/// transcription-api.md: result key = HKDF-SHA256(job key, salt empty, info "orch-transcription result v1").
func resultKey(_ job: SymmetricKey) -> SymmetricKey {
    HKDF<SHA256>.deriveKey(inputKeyMaterial: job, salt: Data(), info: Data("orch-transcription result v1".utf8),
                           outputByteCount: 32)
}

/// 16 kHz mono 16-bit PCM as a WAV file (in memory).
func wav(_ pcm: [Int16]) -> Data {
    let n = UInt32(pcm.count * 2)
    func le32(_ v: UInt32) -> Data { withUnsafeBytes(of: v.littleEndian) { Data($0) } }
    func le16(_ v: UInt16) -> Data { withUnsafeBytes(of: v.littleEndian) { Data($0) } }
    var d = Data("RIFF".utf8); d.append(le32(36 + n)); d.append(Data("WAVEfmt ".utf8))
    d.append(le32(16)); d.append(le16(1)); d.append(le16(1)); d.append(le32(16000)); d.append(le32(32000))
    d.append(le16(2)); d.append(le16(16)); d.append(Data("data".utf8)); d.append(le32(n))
    pcm.withUnsafeBufferPointer { b in d.append(UnsafeBufferPointer(start: UnsafeRawPointer(b.baseAddress!)
        .assumingMemoryBound(to: UInt8.self), count: b.count * 2)) }
    return d
}

/// crypto.md §1 OPF1: "OPF1" | IV 12 | AES-256-GCM(u32 BE N | header JSON | file bytes) | tag 16, AAD "OPF1".
func opf1Seal(name: String, type: String, file: Data, key: SymmetricKey) throws -> Data {
    let head = try JSONSerialization.data(withJSONObject: ["name": name, "type": type, "size": file.count],
                                          options: [.sortedKeys])
    var plain = be32(UInt32(head.count)); plain.append(head); plain.append(file)
    let box = try AES.GCM.seal(plain, using: key, nonce: AES.GCM.Nonce(), authenticating: Data("OPF1".utf8))
    var out = Data("OPF1".utf8)
    out.append(contentsOf: box.nonce); out.append(box.ciphertext); out.append(box.tag)
    return out
}

/// Opens an OPF1 blob; returns (header, file bytes) or nil for "wrong key or broken file".
func opf1Open(_ blob: Data, key: SymmetricKey) -> ([String: Any], Data)? {
    guard blob.count >= 32, blob.prefix(4) == Data("OPF1".utf8) else { return nil }
    let b = Data(blob)
    guard let box = try? AES.GCM.SealedBox(nonce: AES.GCM.Nonce(data: b.subdata(in: 4 ..< 16)),
                                           ciphertext: b.subdata(in: 16 ..< b.count - 16), tag: b.suffix(16)),
          let plain = try? AES.GCM.open(box, using: key, authenticating: Data("OPF1".utf8)), plain.count >= 4
    else { return nil }
    let p = Data(plain)
    let n = Int(p.prefix(4).withUnsafeBytes { $0.loadUnaligned(as: UInt32.self).bigEndian })
    guard n >= 1, n <= 65536, p.count >= 4 + n,
          let head = try? JSONSerialization.jsonObject(with: p.subdata(in: 4 ..< 4 + n)) as? [String: Any],
          let size = head["size"] as? Int, size == p.count - 4 - n else { return nil }
    return (head, p.subdata(in: 4 + n ..< p.count))
}

struct Line { let start: Double; let end: Double; let who: String; let text: String }

/// The service's transcript of one piece, checked: times inside the piece, bounded text. nil = not in the agreed form.
func pieceLines(_ json: Data, offset: Double, seconds: Double, who: String) -> (String, [Line])? {
    guard let obj = try? JSONSerialization.jsonObject(with: json) as? [String: Any],
          let segs = obj["segments"] as? [Any], segs.count <= maxLines else { return nil }
    var out: [Line] = []
    for s in segs {
        guard let s = s as? [String: Any], let a = (s["start"] as? NSNumber)?.doubleValue,
              let e = (s["end"] as? NSNumber)?.doubleValue, let t = s["text"] as? String,
              a.isFinite, e.isFinite, a >= 0, e >= a, e <= seconds + 5 else { return nil }
        let text = String(t.trimmingCharacters(in: .whitespacesAndNewlines).prefix(4000))
        if text.isEmpty { continue }
        // up to 5 s past the piece's end (rounding in the service) is moved onto its end
        out.append(Line(start: offset + min(a, seconds), end: offset + min(e, seconds), who: who, text: text))
    }
    return ((obj["language"] as? String).map { String($0.prefix(16)) } ?? "", out)
}

/// Both tracks into one transcript: by start time, me first on a tie.
func merged(_ lines: [Line]) -> [Line] {
    lines.sorted { ($0.start, $0.who == "me" ? 0 : 1, $0.end) < ($1.start, $1.who == "me" ? 0 : 1, $1.end) }
}

/// When to try again after the n-th failure in a row (n from 1), or what the service asked for (Retry-After).
func retryDelay(_ n: Int, asked: Double? = nil, testSeconds: Double? = nil) -> Double {
    if let t = testSeconds { return t }
    let base = backoff[min(max(n, 1), backoff.count) - 1]
    if let a = asked, a > 0 { return min(max(a, base), 3600) }
    return base
}

// MARK: - the service

struct Service: Equatable {
    let url: String
    let token: String
    /// Which service and key a job was made with: a job is only asked about with the same one.
    var tag: String { SHA256.hash(data: Data((url + "\n" + token).utf8)).prefix(8).map { String(format: "%02x", $0) }.joined() }
}

/// Reads the service a workspace handed over in its wanted file ({"service": {"url", "token"}}).
func serviceIn(_ file: URL) -> Service? {
    guard let d = try? Data(contentsOf: file), d.count < 8192,
          let o = try? JSONSerialization.jsonObject(with: d) as? [String: Any],
          let s = o["service"] as? [String: Any], let u = s["url"] as? String, let t = s["token"] as? String,
          let url = URL(string: u), ["http", "https"].contains(url.scheme ?? ""), url.host != nil,
          url.user == nil, url.query == nil, url.fragment == nil, t.hasPrefix("ort_"), t.count == 47
    else { return nil }
    return Service(url: u.hasSuffix("/") ? String(u.dropLast()) : u, token: t)
}

enum Reply {
    case ok(Int, Data, [String: String])
    case unreachable
}

final class NoRedirects: NSObject, URLSessionTaskDelegate {
    func urlSession(_ s: URLSession, task: URLSessionTask, willPerformHTTPRedirection r: HTTPURLResponse,
                    newRequest: URLRequest, completionHandler: @escaping (URLRequest?) -> Void) {
        completionHandler(nil)  // never follow a redirect: the key and the token go only to the address set
    }
}

let http: URLSession = {
    let c = URLSessionConfiguration.ephemeral
    c.urlCache = nil
    c.httpCookieStorage = nil
    c.timeoutIntervalForRequest = 60
    return URLSession(configuration: c, delegate: NoRedirects(), delegateQueue: nil)
}()

func call(_ svc: Service, _ method: String, _ path: String, body: Data? = nil, headers: [String: String] = [:],
          timeout: Double = 30) -> Reply {
    guard let url = URL(string: svc.url + path) else { return .unreachable }
    var r = URLRequest(url: url, cachePolicy: .reloadIgnoringLocalAndRemoteCacheData, timeoutInterval: timeout)
    r.httpMethod = method
    r.setValue("Bearer \(svc.token)", forHTTPHeaderField: "Authorization")
    for (k, v) in headers { r.setValue(v, forHTTPHeaderField: k) }
    if let body { r.httpBody = body; r.setValue("application/octet-stream", forHTTPHeaderField: "Content-Type") }
    let done = DispatchSemaphore(value: 0)
    var out = Reply.unreachable
    let task = http.dataTask(with: r) { data, resp, _ in
        if let h = resp as? HTTPURLResponse {
            var hs: [String: String] = [:]
            for (k, v) in h.allHeaderFields { if let k = k as? String, let v = v as? String { hs[k.lowercased()] = v } }
            out = .ok(h.statusCode, data ?? Data(), hs)
        }
        done.signal()
    }
    task.resume()
    done.wait()
    return out
}

func jsonOf(_ d: Data) -> [String: Any] { (try? JSONSerialization.jsonObject(with: d) as? [String: Any]) ?? [:] }

// MARK: - one recording's journal

struct Piece: Codable {
    var track: String  // me | others
    var n: Int
    var start: Double  // seconds from the recording's start
    var seconds: Double
    var job: String?
    var service: String?  // Service.tag the job was made with
    var done = false
    var empty = false
    var fails = 0
}

struct Journal: Codable {
    var v = 1
    var pieces: [Piece] = []
    var downs = 0  // failures in a row of the whole service (unreachable, busy)
    var nextTry: String?
    var state = "waiting"
    var problem: String?
    var language = ""
    var refused: String?  // Service.tag that refused the key: not asked again until the setting changes
    var deletes: [String] = []  // "<Service.tag> <job id>": finished jobs whose DELETE did not go through yet
}

final class Transcriber {
    let home: URL
    let keys: KeyStore
    let queue = DispatchQueue(label: "orch.companion.transcribe")
    let lock = NSLock()
    var running = false
    var nowProblem: String?
    var tryNowAsked = false
    var pieceSeconds = pieceSecondsDefault
    var testRetry: Double?
    var poll: (first: Double, later: Double) = (5, 15)
    var onChange: (() -> Void)?

    init(home: URL, keys: KeyStore) { self.home = home; self.keys = keys }

    /// The sentence the menu and orch show while a transcript waits (nil when nothing waits on a problem).
    var problem: String? { lock.lock(); defer { lock.unlock() }; return nowProblem }

    func tryNow() { lock.lock(); tryNowAsked = true; lock.unlock() }

    /// Called every few seconds: start one pass when none runs. `current` is the recording still being made.
    func poke(current: String?, services: @escaping () -> [String: Service]) {
        lock.lock()
        if running { lock.unlock(); return }
        running = true
        let force = tryNowAsked
        tryNowAsked = false
        lock.unlock()
        queue.async { [weak self] in
            guard let self else { return }
            let p = self.pass(current: current, services: services, force: force)
            self.lock.lock()
            let changed = p != self.nowProblem
            self.nowProblem = p
            self.running = false
            self.lock.unlock()
            if changed { DispatchQueue.main.async { self.onChange?() } }
        }
    }

    var folder: URL { home.appendingPathComponent("recordings") }

    /// One pass over every finished recording without a transcript. Returns the problem to show, if any.
    func pass(current: String?, services: () -> [String: Service], force: Bool) -> String? {
        let fm = FileManager.default
        var shown: String?
        let ids = ((try? fm.contentsOfDirectory(atPath: folder.path)) ?? []).sorted()
        for id in ids where id != current && UUID(uuidString: id) != nil {
            let dir = folder.appendingPathComponent(id)
            let t = readJSON(dir.appendingPathComponent("transcript.json"))
            if let st = t["state"] as? String, st == "done" { continue }
            if (t["state"] as? String) == "failed" && !force {  // not tried by itself again; still said
                if shown == nil { shown = t["problem"] as? String }
                continue
            }
            // The settings are read again for every recording: turning the service off stops the next one.
            if let p = one(id: id, dir: dir, services: services(), force: force), shown == nil { shown = p }
        }
        return shown
    }

    func readJSON(_ url: URL) -> [String: Any] {
        guard let d = try? Data(contentsOf: url), d.count < 64 << 20 else { return [:] }
        return jsonOf(d)
    }

    @discardableResult
    func writeFile(_ dir: URL, _ name: String, _ data: Data) -> Bool {
        let tmp = dir.appendingPathComponent(".\(name).part")
        guard FileManager.default.createFile(atPath: tmp.path, contents: data, attributes: [.posixPermissions: 0o600])
        else { return false }
        if rename(tmp.path, dir.appendingPathComponent(name).path) != 0 {
            try? FileManager.default.removeItem(at: tmp)
            return false
        }
        return true
    }

    func save(_ dir: URL, _ j: Journal) {
        if let d = try? JSONEncoder().encode(j) { writeFile(dir, "journal.json", d) }
    }

    /// transcript.json as step 7 reads it.
    @discardableResult
    func publish(_ dir: URL, id: String, j: Journal, info: [String: Any], lines: [Line]? = nil) -> Bool {
        var o: [String: Any] = ["v": 1, "id": id, "state": j.state, "started": info["started"] ?? "",
                                "minutes": Int(((info["seconds"] as? Double) ?? 0) / 60 + 0.5),
                                "app": info["app"] ?? "Teams", "language": j.language]
        if let p = j.problem { o["problem"] = p }
        if let n = j.nextTry { o["next_try"] = n }
        if let lines {
            o["lines"] = lines.map { ["start": ($0.start * 100).rounded() / 100, "end": ($0.end * 100).rounded() / 100,
                                      "who": $0.who, "text": $0.text] }
        }
        guard let d = try? JSONSerialization.data(withJSONObject: o, options: [.sortedKeys]) else { return false }
        return writeFile(dir, "transcript.json", d)
    }

    func clock(_ d: Date) -> String { let f = DateFormatter(); f.dateFormat = "HH:mm"; return f.string(from: d) }

    /// Wait: the service is down or busy. Keeps everything and says when it tries again.
    func down(_ dir: URL, _ id: String, _ j: inout Journal, _ info: [String: Any], words: String, asked: Double?) -> String {
        j.downs += 1
        let at = Date().addingTimeInterval(retryDelay(j.downs, asked: asked, testSeconds: testRetry))
        j.nextTry = iso.string(from: at)
        j.problem = words + " orch Companion tries again at \(clock(at)). The recording is kept."
        j.state = "waiting"
        save(dir, j); publish(dir, id: id, j: j, info: info)
        return j.problem!
    }

    /// Wait for a person: no service, or the key was refused. Tried again when the setting changes or on Try again.
    func blocked(_ dir: URL, _ id: String, _ j: inout Journal, _ info: [String: Any], _ words: String) -> String {
        j.problem = words + " The recording is kept."
        j.nextTry = nil
        j.state = "waiting"
        save(dir, j); publish(dir, id: id, j: j, info: info)
        return j.problem!
    }

    /// Plan the pieces of both tracks (once). nil when the recording cannot be read or was not agreed.
    func plan(_ dir: URL, key: SymmetricKey) -> [Piece]? {
        var pieces: [Piece] = []
        for t in [Track.me, .others] {
            var end: UInt64 = 0
            let r = readTrack(dir.appendingPathComponent(t.file), key: key, expect: t) { start, pcm in
                guard start < UInt64(24 * 3600 * sampleRate) else { return }
                end = max(end, start + UInt64(pcm.count))
            }
            guard ["complete", "cut off"].contains(r["state"] as? String ?? ""),
                  (r["recording"] as? String) == dir.lastPathComponent,
                  ((r["details"] as? [String: Any])?["consent"] as? String) == "agreed" else { return nil }
            let total = Double(end) / sampleRate
            var n = 0, at = 0.0
            while at < total {
                pieces.append(Piece(track: t == .me ? "me" : "others", n: n, start: at, seconds: min(pieceSeconds, total - at)))
                n += 1; at += pieceSeconds
            }
        }
        return pieces
    }

    /// One piece's audio on the recording's timeline (gaps as silence), only that window in memory.
    func audio(_ dir: URL, key: SymmetricKey, _ p: Piece) -> [Int16]? {
        let first = UInt64(p.start * sampleRate), count = Int(p.seconds * sampleRate)
        var pcm = [Int16](repeating: 0, count: count)
        let t: Track = p.track == "me" ? .me : .others
        let r = readTrack(dir.appendingPathComponent(t.file), key: key, expect: t) { start, s in
            guard start + UInt64(s.count) > first, start < first + UInt64(count) else { return }
            for (i, v) in s.enumerated() {
                let at = Int64(start) + Int64(i) - Int64(first)
                if at >= 0 && at < Int64(count) { pcm[Int(at)] = v }
            }
        }
        guard ["complete", "cut off"].contains(r["state"] as? String ?? "") else { return nil }
        return pcm
    }

    func jobKeyId(_ id: String, _ p: Piece) -> String { "\(id).job.\(p.track).\(p.n)" }

    /// Moves one recording on as far as it goes now. Returns the problem to show, if any.
    func one(id: String, dir: URL, services: [String: Service], force: Bool) -> String? {
        let info = readJSON(dir.appendingPathComponent("info.json"))
        if (info["state"] as? String) == "recording" && current(id) { return nil }
        var j = (try? Data(contentsOf: dir.appendingPathComponent("journal.json")))
            .flatMap { try? JSONDecoder().decode(Journal.self, from: $0) } ?? Journal()
        if force { j.downs = 0; j.nextTry = nil; if j.state == "failed" { j.state = "waiting"; for i in j.pieces.indices { j.pieces[i].fails = 0 } } }
        if let n = j.nextTry, let at = iso.date(from: n), at > Date() { return j.problem }
        guard let key = keys.get(id) else {
            j.state = "failed"; j.problem = "The transcript could not be made: the recording's key is missing."
            save(dir, j); publish(dir, id: id, j: j, info: info); return j.problem
        }
        // The workspace this recording was made for (authenticated in the recording), else none.
        let forWs = (readTrack(dir.appendingPathComponent(Track.me.file), key: key, expect: .me)["details"]
            as? [String: Any])?["for"] as? [String] ?? []
        let candidates = forWs.compactMap { services[$0] }
        guard let svc = candidates.first else {
            return blocked(dir, id, &j, info, "Transcript waits: no transcription service is set up in orch.")
        }
        // Several workspaces wanted this call and they send to different services: never pick one by order.
        if candidates.contains(where: { $0 != svc }) {
            return blocked(dir, id, &j, info, "Transcript waits: the workspaces that wanted this call use different "
                + "transcription services. Turn it off in all but one.")
        }
        if j.refused == svc.tag && !force { return j.problem }
        j.refused = nil
        if j.pieces.isEmpty {
            guard let planned = plan(dir, key: key) else {
                j.state = "failed"; j.problem = "The transcript could not be made: the recording cannot be read."
                save(dir, j); publish(dir, id: id, j: j, info: info); return j.problem
            }
            j.pieces = planned
            save(dir, j)
        }
        j.deletes = j.deletes.filter { row in
            let parts = row.split(separator: " ", maxSplits: 1).map(String.init)
            guard parts.count == 2, parts[0] == svc.tag else { return parts.count == 2 }
            return !deleted(svc, parts[1])
        }
        save(dir, j)
        for i in j.pieces.indices where !j.pieces[i].done {
            switch piece(id: id, dir: dir, svc: svc, i, &j) {
            case .next: j.downs = 0; save(dir, j)
            case .down(let busy, let asked):
                return down(dir, id, &j, info, words: busy ? "Transcript waits: the transcription service is busy."
                    : "Transcript waits: the transcription service cannot be reached.", asked: asked)
            case .refused:
                j.refused = svc.tag
                return blocked(dir, id, &j, info, "Transcript waits: the transcription service did not accept this workspace's key.")
            case .failed:
                if j.pieces[i].fails >= maxPieceFails {
                    j.state = "failed"; j.nextTry = nil
                    j.problem = "The transcript could not be made. The recording is kept."
                    save(dir, j); publish(dir, id: id, j: j, info: info); return j.problem
                }
                return down(dir, id, &j, info, words: "Transcript waits: a part could not be transcribed.", asked: nil)
            }
        }
        // Every piece done: one transcript of both tracks.
        var lines: [Line] = []
        for i in j.pieces.indices where !j.pieces[i].empty {
            let p = j.pieces[i]
            let f = dir.appendingPathComponent("piece-\(p.track)-\(p.n).json")
            guard let o = (try? Data(contentsOf: f)).flatMap({ try? JSONSerialization.jsonObject(with: $0) as? [String: Any] })
            else {  // a piece's text went missing: that piece again
                j.pieces[i].done = false
                return down(dir, id, &j, info, words: "Transcript waits: a part has to be sent again.", asked: nil)
            }
            for l in o["lines"] as? [[String: Any]] ?? [] {
                if let a = l["start"] as? Double, let e = l["end"] as? Double, let t = l["text"] as? String {
                    lines.append(Line(start: a, end: e, who: p.track, text: t))
                }
            }
        }
        j.state = "done"; j.problem = nil; j.nextTry = nil
        guard publish(dir, id: id, j: j, info: info, lines: merged(lines)) else {
            j.state = "waiting"
            return down(dir, id, &j, info, words: "Transcript waits: it could not be written to the disk.", asked: nil)
        }
        save(dir, j)
        for p in j.pieces { try? FileManager.default.removeItem(at: dir.appendingPathComponent("piece-\(p.track)-\(p.n).json")) }
        return nil
    }

    var currentId: () -> String? = { nil }
    func current(_ id: String) -> Bool { currentId() == id }

    enum Step { case next, down(busy: Bool, asked: Double?), refused, failed }

    func retryAfter(_ h: [String: String]) -> Double? { h["retry-after"].flatMap { Double($0) } }

    func jobPath(_ jid: String) -> String {
        "/v1/jobs/" + (jid.addingPercentEncoding(withAllowedCharacters: .alphanumerics) ?? jid)
    }

    /// DELETE a finished job; true when it is gone (204, or 404: already gone).
    func deleted(_ svc: Service, _ jid: String) -> Bool {
        if case .ok(let c, _, _) = call(svc, "DELETE", jobPath(jid)) { return c == 204 || c == 404 }
        return false
    }

    /// The same sorting of an answer for every call: nil = fine (2xx or what the caller handles itself).
    func classify(_ code: Int, _ h: [String: String]) -> Step? {
        switch code {
        case 401: return .refused
        case 429, 503: return .down(busy: true, asked: retryAfter(h))
        case 500...599: return .down(busy: false, asked: retryAfter(h))
        default: return nil
        }
    }

    func forget(_ svc: Service, _ jid: String, _ j: inout Journal) {
        if !deleted(svc, jid) { j.deletes.append("\(svc.tag) \(jid)") }  // tried again on the next pass
    }

    /// One piece: upload (or go on with its open job), wait, fetch, decrypt, keep its lines, delete the job.
    func piece(id: String, dir: URL, svc: Service, _ i: Int, _ j: inout Journal) -> Step {
        var p = j.pieces[i]
        defer { j.pieces[i] = p }
        let kid = jobKeyId(id, p)
        if p.job != nil && p.service != svc.tag {
            // Made with another service or key: never ask the new one about it; start this piece again.
            p.job = nil; keys.remove(kid)
        }
        if p.job == nil {
            guard let rkey = keys.get(id), let pcm = audio(dir, key: rkey, p) else { p.fails = maxPieceFails; return .failed }
            if !pcm.contains(where: { $0 != 0 }) {  // nothing but silence (gaps): no job needed
                p.done = true; p.empty = true; return .next
            }
            let jk = SymmetricKey(size: .bits256)
            guard keys.put(kid, jk), let blob = try? opf1Seal(name: "\(p.track)-\(p.n + 1).wav", type: "audio/wav",
                                                                file: wav(pcm), key: jk)
            else { p.fails += 1; return .failed }
            let k64 = jk.withUnsafeBytes { b64url(Data($0)) }
            switch call(svc, "POST", "/v1/jobs", body: blob, headers: ["X-Orch-Job-Key": k64], timeout: 600) {
            case .unreachable: keys.remove(kid); return .down(busy: false, asked: nil)
            case .ok(let code, let body, let h):
                switch code {
                case 202:
                    guard let jid = jsonOf(body)["id"] as? String, !jid.isEmpty, jid.count < 128 else { p.fails += 1; return .failed }
                    p.job = jid; p.service = svc.tag
                    j.pieces[i] = p
                    save(dir, j)  // the job id is on disk before anything else can stop us
                case 401: keys.remove(kid); return .refused
                case 429, 503: keys.remove(kid); return .down(busy: true, asked: retryAfter(h))
                case 500...599: keys.remove(kid); return .down(busy: false, asked: retryAfter(h))
                default: keys.remove(kid); p.fails += 1; return .failed  // 413, 415, 422: this audio, not the service
                }
            }
        }
        guard let jid = p.job, let jk = keys.get(kid) else { p.job = nil; p.fails += 1; return .failed }
        let path = jobPath(jid)
        let began = Date()
        while true {
            switch call(svc, "GET", path) {
            case .unreachable: return .down(busy: false, asked: nil)
            case .ok(let code, let body, let h):
                if let step = classify(code, h) { return step }
                if code == 404 { p.job = nil; keys.remove(kid); p.fails += 1; return .failed }  // expired or gone
                guard code == 200 else { p.fails += 1; return .failed }
                switch jsonOf(body)["status"] as? String ?? "" {
                case "done":
                    switch fetch(svc, path, jk: jk, p) {
                    case .lines(let lang, let lines):
                        let o: [String: Any] = ["lines": lines.map { ["start": $0.start, "end": $0.end, "text": $0.text] }]
                        guard let d = try? JSONSerialization.data(withJSONObject: o),
                              writeFile(dir, "piece-\(p.track)-\(p.n).json", d)
                        else {  // kept on the service: fetched again on the next try
                            return .down(busy: false, asked: nil)
                        }
                        if j.language.isEmpty { j.language = lang }
                        p.done = true
                        p.job = nil; keys.remove(kid)
                        forget(svc, jid, &j)
                        return .next
                    case .step(let step):
                        return step
                    case .bad:  // not in the agreed form: this piece again
                        p.job = nil; keys.remove(kid); p.fails += 1
                        forget(svc, jid, &j)
                        return .failed
                    }
                case "failed":
                    p.job = nil; keys.remove(kid); p.fails += 1
                    forget(svc, jid, &j)
                    return .failed
                case "needs_key":
                    let k64 = jk.withUnsafeBytes { b64url(Data($0)) }
                    switch call(svc, "POST", path + "/key", headers: ["X-Orch-Job-Key": k64]) {
                    case .unreachable: return .down(busy: false, asked: nil)
                    case .ok(let c, _, let h):
                        if let step = classify(c, h) { return step }
                        if c == 404 || c == 422 { p.job = nil; keys.remove(kid); p.fails += 1; return .failed }
                    }
                default: break  // waiting, running
                }
            }
            Thread.sleep(forTimeInterval: Date().timeIntervalSince(began) < 60 ? poll.first : poll.later)
        }
    }

    enum Fetched { case lines(String, [Line]), step(Step), bad }

    /// The finished job's transcript, decrypted and checked.
    func fetch(_ svc: Service, _ path: String, jk: SymmetricKey, _ p: Piece) -> Fetched {
        switch call(svc, "GET", path + "/result", timeout: 120) {
        case .unreachable: return .step(.down(busy: false, asked: nil))
        case .ok(let code, let blob, let h):
            if let step = classify(code, h) { return .step(step) }
            guard code == 200, blob.count <= maxResultBytes,
                  let (head, file) = opf1Open(blob, key: resultKey(jk)), (head["type"] as? String) == "application/json",
                  let (lang, lines) = pieceLines(file, offset: p.start, seconds: p.seconds, who: p.track)
            else { return .bad }
            return .lines(lang, lines)
        }
    }
}

// MARK: - selftest

func transcribeSelftest() -> Int {
    var failed = 0
    func check(_ ok: Bool, _ what: String) { if ok { print("ok   \(what)") } else { failed += 1; print("FAIL \(what)") } }
    let vectors: [(String, String)] = [
        ("AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8", "E6zRcgR0rWFYI8YyOFweje7QGAAMG6Sa83ezktdx3YY"),
        ("AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", "w0y01qgohfG6r_VUWESWoMZCcaklOPOSbeXuOxUg_ec"),
        ("__________________________________________8", "iTRICgm9GTALtezqdOvPtj13yDyInZW06eugr5c3i_0"),
    ]
    check(vectors.allSatisfy { jk, rk in
        unb64url(jk).map { resultKey(SymmetricKey(data: $0)).withUnsafeBytes { b64url(Data($0)) } } == rk
    }, "result key matches the transcription vectors")
    let k = SymmetricKey(size: .bits256)
    let w = wav([1, -1, 2])
    check(w.count == 50 && w.prefix(4) == Data("RIFF".utf8) && w[w.startIndex + 40] == 6, "WAV header and length")
    if let blob = try? opf1Seal(name: "me-1.wav", type: "audio/wav", file: w, key: k),
       let (h, f) = opf1Open(blob, key: k) {
        check(f == w && (h["type"] as? String) == "audio/wav", "OPF1 seal and open")
        var bad = blob; bad[bad.startIndex + 20] ^= 1
        check(opf1Open(bad, key: k) == nil && opf1Open(blob, key: SymmetricKey(size: .bits256)) == nil,
              "OPF1 refuses a changed blob and a wrong key")
    } else { check(false, "OPF1 seal and open") }
    let good = Data(#"{"language":"de","segments":[{"start":1.5,"end":2,"text":" Hallo "},{"start":3,"end":3,"text":""}]}"#.utf8)
    let got = pieceLines(good, offset: 1800, seconds: 1800, who: "others")
    check(got?.0 == "de" && got?.1.count == 1 && got?.1.first?.start == 1801.5 && got?.1.first?.text == "Hallo",
          "piece times move to the recording's timeline")
    check(pieceLines(Data(#"{"segments":[{"start":5,"end":4,"text":"x"}]}"#.utf8), offset: 0, seconds: 10, who: "me") == nil
          && pieceLines(Data(#"{"segments":[{"start":0,"end":99,"text":"x"}]}"#.utf8), offset: 0, seconds: 10, who: "me") == nil,
          "reversed or out-of-piece times are refused")
    let over = pieceLines(Data(#"{"segments":[{"start":12,"end":13,"text":"x"}]}"#.utf8), offset: 0, seconds: 10, who: "me")
    check(over?.1.first.map { $0.start == 10 && $0.end == 10 } == true, "a little past the piece end moves onto its end")
    let m = merged([Line(start: 2, end: 3, who: "others", text: "b"), Line(start: 2, end: 3, who: "me", text: "a"),
                    Line(start: 1, end: 2, who: "others", text: "c")])
    check(m.map(\.text) == ["c", "a", "b"], "both tracks by time, me first on a tie")
    check(retryDelay(1) == 60 && retryDelay(9) == 3600 && retryDelay(1, asked: 7200) == 3600 && retryDelay(2, asked: 10) == 120,
          "retry times")
    check(serviceIn(URL(fileURLWithPath: "/nonexistent")) == nil, "no wanted file, no service")
    return failed
}
