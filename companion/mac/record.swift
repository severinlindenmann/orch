// orch Companion, step 4 (ORCH-1195): record the call into two encrypted tracks. Design: ORCH-1267
// recording-design.md. Audio is written to disk only encrypted (AES-256-GCM, a new key per recording, kept in the
// Keychain). Audio callbacks only copy samples; converting, encrypting and writing run on one worker queue.
//
//   recordings/<id>/me.ocr, others.ocr   "OCR1" | track u8 | id 16 bytes | frames
//   frame   = u32 BE n | nonce 12 | n bytes ciphertext+tag
//   nonce   = u32 BE track | u64 BE counter;  AAD = "OCR1" | track | id | u64 BE counter
//   plain   = kind u8 | payload: 0 details JSON, 1 audio (u64 BE start sample | s16le PCM 16 kHz mono),
//             2 end (u64 BE frames | u64 BE samples)
//   recordings/<id>/info.json            a hint only (not authenticated, no audio, no key)

import AVFoundation
import CoreAudio
import CryptoKit
import Foundation
import Security

let sampleRate = 16000.0
let maxFrame = 1 << 20
let queueLimit = 600  // about one minute of buffers per track before the recording stops as "too slow"

enum Track: UInt8 { case me = 1, others = 2; var file: String { self == .me ? "me.ocr" : "others.ocr" } }

func be32(_ v: UInt32) -> Data { withUnsafeBytes(of: v.bigEndian) { Data($0) } }
func be64(_ v: UInt64) -> Data { withUnsafeBytes(of: v.bigEndian) { Data($0) } }

// MARK: - keys

protocol KeyStore {
    func put(_ id: String, _ key: SymmetricKey) -> Bool
    func get(_ id: String) -> SymmetricKey?
    func remove(_ id: String)
}

struct KeychainStore: KeyStore {
    let service = "orch Companion recordings"
    func query(_ id: String) -> [String: Any] {
        [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service,
         kSecAttrAccount as String: id]
    }
    func put(_ id: String, _ key: SymmetricKey) -> Bool {
        var q = query(id)
        q[kSecValueData as String] = key.withUnsafeBytes { Data($0) }
        q[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        SecItemDelete(query(id) as CFDictionary)
        return SecItemAdd(q as CFDictionary, nil) == errSecSuccess
    }
    func get(_ id: String) -> SymmetricKey? {
        var q = query(id)
        q[kSecReturnData as String] = true
        var out: CFTypeRef?
        guard SecItemCopyMatching(q as CFDictionary, &out) == errSecSuccess, let d = out as? Data, d.count == 32
        else { return nil }
        return SymmetricKey(data: d)
    }
    func remove(_ id: String) { SecItemDelete(query(id) as CFDictionary) }
}

/// Tests only: keys as files in a folder, used only with --headless and ORCH_COMPANION_TEST_KEYS.
struct FileKeyStore: KeyStore {
    let dir: URL
    func put(_ id: String, _ key: SymmetricKey) -> Bool {
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return FileManager.default.createFile(atPath: dir.appendingPathComponent(id).path,
                                              contents: key.withUnsafeBytes { Data($0) },
                                              attributes: [.posixPermissions: 0o600])
    }
    func get(_ id: String) -> SymmetricKey? {
        guard let d = FileManager.default.contents(atPath: dir.appendingPathComponent(id).path), d.count == 32
        else { return nil }
        return SymmetricKey(data: d)
    }
    func remove(_ id: String) { try? FileManager.default.removeItem(at: dir.appendingPathComponent(id)) }
}

// MARK: - one encrypted track

final class TrackWriter {
    let track: Track
    let idBytes: Data
    let key: SymmetricKey
    let handle: FileHandle
    var counter: UInt64 = 0
    var failed = false  // after any write error nothing more is written (a nonce is never used twice)
    var audioFrames: UInt64 = 0
    var samples: UInt64 = 0

    init?(folder: URL, track: Track, idBytes: Data, key: SymmetricKey) {
        let url = folder.appendingPathComponent(track.file)
        var head = Data("OCR1".utf8)
        head.append(track.rawValue)
        head.append(idBytes)
        guard FileManager.default.createFile(atPath: url.path, contents: head, attributes: [.posixPermissions: 0o600]),
              let h = try? FileHandle(forWritingTo: url) else { return nil }
        h.seekToEndOfFile()
        self.track = track
        self.idBytes = idBytes
        self.key = key
        handle = h
    }

    func frame(kind: UInt8, _ payload: Data) throws {
        guard !failed else { throw CaptureError.files }
        let counter = self.counter
        self.counter += 1
        var aad = Data("OCR1".utf8)
        aad.append(track.rawValue)
        aad.append(idBytes)
        aad.append(be64(counter))
        var nonceBytes = be32(UInt32(track.rawValue))
        nonceBytes.append(be64(counter))
        var plain = Data([kind])
        plain.append(payload)
        let box = try AES.GCM.seal(plain, using: key, nonce: try AES.GCM.Nonce(data: nonceBytes),
                                   authenticating: aad)
        let body = box.ciphertext + box.tag
        var out = be32(UInt32(body.count))
        out.append(nonceBytes)
        out.append(body)
        do { try handle.write(contentsOf: out) } catch { failed = true; throw error }
    }

    func details(_ obj: [String: Any]) throws {
        try frame(kind: 0, try JSONSerialization.data(withJSONObject: obj, options: [.sortedKeys]))
    }

    func audio(start: UInt64, pcm: [Int16]) throws {
        var payload = be64(start)
        pcm.withUnsafeBufferPointer { b in
            for s in b { withUnsafeBytes(of: s.littleEndian) { payload.append(contentsOf: $0) } }
        }
        try frame(kind: 1, payload)
        audioFrames += 1
        samples += UInt64(pcm.count)
    }

    func end() throws {
        guard !failed else { try? handle.close(); throw CaptureError.files }
        var payload = be64(audioFrames)
        payload.append(be64(samples))
        try frame(kind: 2, payload)
        try handle.synchronize()
        try handle.close()
    }
}

// MARK: - sources: copy samples out of the audio callback, nothing else

/// What a capture hands the worker (always called on the recording's worker queue): which track, when (seconds
/// since the recording started), 16 kHz mono samples.
typealias Deliver = (Track, Double, [Int16]) -> Void

/// Buffers handed from audio callbacks to the worker but not written yet; over the limit the recording stops.
final class Backlog {
    let lock = NSLock()
    var n = 0
    var over: () -> Void = {}
    func add() -> Bool {
        lock.lock(); defer { lock.unlock() }
        if n >= queueLimit * 2 { DispatchQueue.global().async(execute: over); return false }
        n += 1
        return true
    }
    func done() { lock.lock(); n -= 1; lock.unlock() }
}

protocol Capture { func start(_ deliver: @escaping Deliver) throws; func stop() }

/// Tests: 440 Hz for me, 660 Hz for others, 100 ms buffers, so the whole path runs without audio devices.
final class FakeCapture: Capture {
    var timer: DispatchSourceTimer?
    let q: DispatchQueue
    init(work: DispatchQueue) { q = work }
    func start(_ deliver: @escaping Deliver) throws {
        var n = 0
        let t = DispatchSource.makeTimerSource(queue: q)
        t.schedule(deadline: .now(), repeating: .milliseconds(100))
        t.setEventHandler {
            for (track, hz) in [(Track.me, 440.0), (Track.others, 660.0)] {
                let base = n * 1600
                let pcm = (0..<1600).map { i in Int16(8000 * sin(2 * .pi * hz * Double(base + i) / sampleRate)) }
                deliver(track, Double(base) / sampleRate, pcm)
            }
            n += 1
        }
        t.resume()
        timer = t
    }
    func stop() { timer?.cancel(); timer = nil }
}

/// Converts any float/int PCM buffer to 16 kHz mono s16 (on the worker, not in the callback).
final class To16k {
    var converter: AVAudioConverter?
    var from: AVAudioFormat?
    let out = AVAudioFormat(commonFormat: .pcmFormatInt16, sampleRate: sampleRate, channels: 1, interleaved: true)!

    func convert(_ buf: AVAudioPCMBuffer) -> [Int16] {
        if from == nil || from! != buf.format {
            from = buf.format
            converter = AVAudioConverter(from: buf.format, to: out)
        }
        guard let c = converter else { return [] }
        let cap = AVAudioFrameCount(Double(buf.frameLength) * sampleRate / buf.format.sampleRate) + 32
        guard let dst = AVAudioPCMBuffer(pcmFormat: out, frameCapacity: cap) else { return [] }
        var given = false
        var err: NSError?
        c.convert(to: dst, error: &err) { _, status in
            if given { status.pointee = .noDataNow; return nil }
            given = true
            status.pointee = .haveData
            return buf
        }
        guard err == nil, let p = dst.int16ChannelData else { return [] }
        return Array(UnsafeBufferPointer(start: p[0], count: Int(dst.frameLength)))
    }
}

/// My microphone: AVAudioEngine input; a configuration change (AirPods, new default microphone) rebuilds it.
final class MicCapture: Capture {
    let engine = AVAudioEngine()
    let started: UInt64
    let work: DispatchQueue
    let conv = To16k()
    let backlog: Backlog
    var deliver: Deliver?
    var onFail: ((String) -> Void)?
    var observer: NSObjectProtocol?
    init(startedHostTime: UInt64, work: DispatchQueue, backlog: Backlog) {
        started = startedHostTime
        self.work = work
        self.backlog = backlog
    }

    func start(_ deliver: @escaping Deliver) throws {
        self.deliver = deliver
        try install()
        observer = NotificationCenter.default.addObserver(forName: .AVAudioEngineConfigurationChange, object: engine,
                                                          queue: nil) { [weak self] _ in
            self?.work.async {
                do { try self?.install() } catch { self?.onFail?("the microphone could not be recorded") }
            }
        }
    }

    func install() throws {
        engine.stop()
        let input = engine.inputNode
        input.removeTap(onBus: 0)
        let fmt = input.outputFormat(forBus: 0)
        input.installTap(onBus: 0, bufferSize: 4096, format: fmt) { [weak self] buf, when in
            guard let self, self.backlog.add() else { return }
            guard let copy = copyBuffer(buf) else { self.backlog.done(); return }
            let t = AVAudioTime.seconds(forHostTime: when.hostTime) - AVAudioTime.seconds(forHostTime: self.started)
            self.work.async { defer { self.backlog.done() }; self.deliver?(.me, t, self.conv.convert(copy)) }
        }
        try engine.start()
    }

    func stop() {
        if let o = observer { NotificationCenter.default.removeObserver(o) }
        engine.inputNode.removeTap(onBus: 0)
        engine.stop()
    }
}

func copyBuffer(_ b: AVAudioPCMBuffer) -> AVAudioPCMBuffer? {
    guard let c = AVAudioPCMBuffer(pcmFormat: b.format, frameCapacity: b.frameLength) else { return nil }
    c.frameLength = b.frameLength
    let src = UnsafeMutableAudioBufferListPointer(b.mutableAudioBufferList)
    let dst = UnsafeMutableAudioBufferListPointer(c.mutableAudioBufferList)
    for i in 0..<min(src.count, dst.count) {
        if let s = src[i].mData, let d = dst[i].mData { memcpy(d, s, Int(min(src[i].mDataByteSize, dst[i].mDataByteSize))) }
    }
    return c
}

/// The call's sound: a Core Audio process tap on the call app's audio processes (macOS 14.2+), through a private
/// aggregate device. The processes are looked up again every 2 s and the tap rebuilt when they change.
final class CallSoundCapture: Capture {
    let bundles: Set<String>
    let started: UInt64
    let work: DispatchQueue
    let conv = To16k()
    var tap = AudioObjectID(kAudioObjectUnknown)
    var agg = AudioObjectID(kAudioObjectUnknown)
    var proc: AudioDeviceIOProcID?
    var format: AVAudioFormat?
    var current: [AudioObjectID] = []
    var timer: DispatchSourceTimer?
    var deliver: Deliver?
    var onFail: ((String) -> Void)?
    let backlog: Backlog
    let lock = NSLock()
    var stopped = false

    init(bundles: Set<String>, startedHostTime: UInt64, work: DispatchQueue, backlog: Backlog) {
        self.bundles = bundles
        started = startedHostTime
        self.work = work
        self.backlog = backlog
    }

    func objects() -> [AudioObjectID] {
        audioProcesses().filter { bundles.contains($0.bundle) }.map { $0.object }.sorted()
    }

    func start(_ deliver: @escaping Deliver) throws {
        self.deliver = deliver
        try rebuild()
        let t = DispatchSource.makeTimerSource(queue: work)
        t.schedule(deadline: .now() + 2, repeating: 2)
        t.setEventHandler { [weak self] in
            guard let self, self.objects() != self.current else { return }
            do { try self.rebuild() } catch { self.onFail?("the call's sound could not be recorded") }
        }
        t.resume()
        timer = t
    }

    func rebuild() throws {
        lock.lock(); defer { lock.unlock() }
        guard !stopped else { return }
        teardownLocked()
        let next = objects()
        guard !next.isEmpty else { current = next; return }
        let desc = CATapDescription(stereoMixdownOfProcesses: next)
        desc.isPrivate = true
        desc.muteBehavior = .unmuted
        guard AudioHardwareCreateProcessTap(desc, &tap) == noErr else { throw CaptureError.tap }
        var asbd = AudioStreamBasicDescription()
        var addr = AudioObjectPropertyAddress(mSelector: kAudioTapPropertyFormat, mScope: kAudioObjectPropertyScopeGlobal,
                                              mElement: kAudioObjectPropertyElementMain)
        var size = UInt32(MemoryLayout<AudioStreamBasicDescription>.size)
        guard AudioObjectGetPropertyData(tap, &addr, 0, nil, &size, &asbd) == noErr,
              let fmt = AVAudioFormat(streamDescription: &asbd) else { throw CaptureError.tap }
        format = fmt
        let uid = desc.uuid.uuidString
        let aggDesc: [String: Any] = [
            kAudioAggregateDeviceNameKey: "orch Companion call sound",
            kAudioAggregateDeviceUIDKey: UUID().uuidString,
            kAudioAggregateDeviceIsPrivateKey: true,
            kAudioAggregateDeviceIsStackedKey: false,
            kAudioAggregateDeviceTapAutoStartKey: true,
            kAudioAggregateDeviceTapListKey: [[kAudioSubTapUIDKey: uid, kAudioSubTapDriftCompensationKey: true]],
        ]
        guard AudioHardwareCreateAggregateDevice(aggDesc as CFDictionary, &agg) == noErr else { throw CaptureError.tap }
        let st = AudioDeviceCreateIOProcIDWithBlock(&proc, agg, nil) { [weak self] _, inData, inTime, _, _ in
            guard let self, let fmt = self.format, self.backlog.add() else { return }
            guard let buf = AVAudioPCMBuffer(pcmFormat: fmt, bufferListNoCopy: inData, deallocator: nil),
                  let copy = copyBuffer(buf) else { self.backlog.done(); return }
            let t = AVAudioTime.seconds(forHostTime: inTime.pointee.mHostTime)
                - AVAudioTime.seconds(forHostTime: self.started)
            self.work.async { defer { self.backlog.done() }; self.deliver?(.others, t, self.conv.convert(copy)) }
        }
        guard st == noErr, let p = proc, AudioDeviceStart(agg, p) == noErr else { teardownLocked(); throw CaptureError.tap }
        current = next
    }

    func teardownLocked() {
        if let p = proc { AudioDeviceStop(agg, p); AudioDeviceDestroyIOProcID(agg, p) }
        proc = nil
        if agg != kAudioObjectUnknown { AudioHardwareDestroyAggregateDevice(agg) }
        if tap != kAudioObjectUnknown { AudioHardwareDestroyProcessTap(tap) }
        agg = AudioObjectID(kAudioObjectUnknown)
        tap = AudioObjectID(kAudioObjectUnknown)
    }

    func stop() {
        timer?.cancel()
        lock.lock(); stopped = true; teardownLocked(); lock.unlock()
    }
}

enum CaptureError: Error { case tap, key, files }

// MARK: - one recording

final class Recording {
    let id: String
    let folder: URL
    let work = DispatchQueue(label: "orch.companion.recording")
    var writers: [Track: TrackWriter] = [:]
    var captures: [Capture] = []
    let backlog = Backlog()
    var stoppedWhy: String?
    let gate = NSLock()
    var closing = false
    let finished = DispatchSemaphore(value: 0)
    var isClosing: Bool { gate.lock(); defer { gate.unlock() }; return closing }
    let onStop: (String) -> Void
    let startedAt = Date()
    let forWs: [String]  // the workspaces that used Companion when it started (authenticated in the tracks)
    var info: [String: Any]
    /// Spans (seconds since the start) while someone joined and had not agreed: no audio of them is kept.
    var pauses: [(from: Double, to: Double?)] = []
    var isPaused: Bool { gate.lock(); defer { gate.unlock() }; return pauses.last.map { $0.to == nil } ?? false }

    /// Starts recording now. Throws (and records nothing) when the key cannot be kept or a capture cannot start.
    init(home: URL, keys: KeyStore, app: String, bundles: Set<String>, consentAt: Date, fake: Bool,
         forWorkspaces: [String] = [], onStop: @escaping (String) -> Void) throws {
        let uuid = UUID()
        id = uuid.uuidString.lowercased()
        forWs = forWorkspaces
        let idBytes = withUnsafeBytes(of: uuid.uuid) { Data($0) }
        folder = home.appendingPathComponent("recordings").appendingPathComponent(id)
        self.onStop = onStop
        info = ["v": 1, "id": id, "app": app, "started": iso.string(from: startedAt), "state": "recording",
                "consent": ["answer": "agreed", "at": iso.string(from: consentAt)], "for": forWorkspaces]
        let key = SymmetricKey(size: .bits256)
        guard keys.put(id, key), let back = keys.get(id),
              back.withUnsafeBytes({ Data($0) }) == key.withUnsafeBytes({ Data($0) }) else { throw CaptureError.key }
        let fm = FileManager.default
        try fm.createDirectory(at: folder, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
        chmod(folder.deletingLastPathComponent().path, 0o700)
        for t in [Track.me, .others] {
            guard let w = TrackWriter(folder: folder, track: t, idBytes: idBytes, key: key) else {
                keys.remove(id)
                throw CaptureError.files
            }
            try w.details(["app": app, "started": iso.string(from: startedAt), "consent": "agreed",
                           "consent_at": iso.string(from: consentAt), "recording": id,
                           "track": t == .me ? "me" : "others", "for": forWorkspaces])
            writers[t] = w
        }
        writeInfo()
        let host = mach_absolute_time()
        backlog.over = { [weak self] in self?.stop(why: "the computer was too slow to keep up") }
        let mic = MicCapture(startedHostTime: host, work: work, backlog: backlog)
        let sound = CallSoundCapture(bundles: bundles, startedHostTime: host, work: work, backlog: backlog)
        mic.onFail = { [weak self] why in self?.stop(why: why) }
        sound.onFail = { [weak self] why in self?.stop(why: why) }
        captures = fake ? [FakeCapture(work: work)] : [mic, sound]
        do {
            for c in captures { try c.start { [weak self] t, s, pcm in self?.take(t, s, pcm) } }
        } catch {
            for c in captures { c.stop() }
            stop(why: "could not start the recording")
            throw error
        }
    }

    /// Someone joined: from now on nothing is kept until resume(); a buffer that reaches into a pause is dropped.
    func pause() {
        gate.lock()
        guard !closing, pauses.last.map({ $0.to != nil }) ?? true else { gate.unlock(); return }
        let at = Date().timeIntervalSince(startedAt)
        pauses.append((at, nil))
        gate.unlock()
        work.async { [weak self] in self?.notePauses() }
    }

    /// Everyone agreed again: keep audio from now on.
    func resume() {
        gate.lock()
        guard !closing, let last = pauses.last, last.to == nil else { gate.unlock(); return }
        pauses[pauses.count - 1].to = Date().timeIntervalSince(startedAt)
        gate.unlock()
        work.async { [weak self] in self?.notePauses() }
    }

    /// On the worker queue (info is written there).
    func notePauses() {
        gate.lock(); let p = pauses; gate.unlock()
        info["paused"] = p.map { span -> [String: Any] in
            var o: [String: Any] = ["from": span.from]
            if let to = span.to { o["to"] = to }
            return o
        }
        writeInfo()
    }

    func inPause(_ from: Double, _ to: Double) -> Bool {
        gate.lock(); defer { gate.unlock() }
        return pauses.contains { from < ($0.to ?? .infinity) && to > $0.from }
    }

    /// From a capture, on the worker queue.
    func take(_ t: Track, _ seconds: Double, _ pcm: [Int16]) {
        guard !isClosing, let w = writers[t], !pcm.isEmpty else { return }
        if inPause(seconds, seconds + Double(pcm.count) / sampleRate) { return }
        do { try w.audio(start: UInt64(max(0, seconds) * sampleRate), pcm: pcm) }
        catch { stop(why: "it could not write to the disk") }
    }

    /// Stops taking audio at once (also while the worker is busy writing), then ends both files on the worker.
    func stop(why: String = "the call ended") {
        gate.lock()
        if closing { gate.unlock(); return }
        closing = true
        gate.unlock()
        let caps = captures
        DispatchQueue.global(qos: .userInitiated).async { for c in caps { c.stop() } }
        work.async { [weak self] in
            guard let self else { return }
            defer { self.finished.signal() }
            self.stoppedWhy = why
            var ok = true
            for w in self.writers.values { do { try w.end() } catch { ok = false } }
            self.info["state"] = ok && ["the call ended", "you stopped it", "not everyone agreed"].contains(why) ? "done" : "stopped"
            self.info["why"] = why
            self.info["ended"] = iso.string(from: Date())
            self.info["seconds"] = Double(self.writers[.me]?.samples ?? 0) / sampleRate
            self.writeInfo()
            self.onStop(why)
        }
    }

    /// For quitting and updates: stop and wait (at most `seconds`) until both files are ended.
    func stopAndWait(why: String, seconds: Double = 5) {
        stop(why: why)
        _ = finished.wait(timeout: .now() + seconds)
    }

    func writeInfo() {
        guard let d = try? JSONSerialization.data(withJSONObject: info, options: [.sortedKeys]) else { return }
        let tmp = folder.appendingPathComponent(".info.part")
        FileManager.default.createFile(atPath: tmp.path, contents: d, attributes: [.posixPermissions: 0o600])
        _ = rename(tmp.path, folder.appendingPathComponent("info.json").path)
    }
}

// MARK: - reading a recording back (tests now, sending it on in step 6)

/// Reads one track with every check: "complete" (end frame, totals match), "cut off" (whole frames up to a crash,
/// no end frame) or "broken" (anything else: wrong key, a changed, missing, doubled or swapped frame).
func readTrack(_ url: URL, key: SymmetricKey, expect: Track, onAudio: ((UInt64, [Int16]) -> Void)? = nil)
    -> [String: Any] {
    guard let data = try? Data(contentsOf: url, options: .alwaysMapped), data.count >= 21,
          data.prefix(4) == Data("OCR1".utf8), let track = Track(rawValue: data[data.startIndex + 4])
    else { return ["state": "broken", "why": "not a recording"] }
    guard track == expect else { return ["state": "broken", "why": "the other track"] }
    let idBytes = data.subdata(in: data.startIndex + 5 ..< data.startIndex + 21)
    var at = data.startIndex + 21
    var counter: UInt64 = 0
    var frames: UInt64 = 0, samples: UInt64 = 0
    var details: Any = NSNull()
    var crossings = 0
    var last: Int16 = 0
    var next: UInt64? = nil
    var gaps: [[Double]] = []  // [from, to] seconds with no audio (paused while someone had not agreed)
    func broken(_ why: String) -> [String: Any] { ["state": "broken", "why": why, "frame": counter] }
    while at < data.endIndex {
        guard data.endIndex - at >= 16 else { return cut() }
        let n = Int(data.subdata(in: at ..< at + 4).withUnsafeBytes { $0.loadUnaligned(as: UInt32.self).bigEndian })
        guard n >= 17, n <= maxFrame else { return broken("frame size") }
        guard data.endIndex - at >= 16 + n else { return cut() }
        let nonceBytes = data.subdata(in: at + 4 ..< at + 16)
        var want = be32(UInt32(track.rawValue)); want.append(be64(counter))
        guard nonceBytes == want else { return broken("frame order") }
        let body = data.subdata(in: at + 16 ..< at + 16 + n)
        var aad = Data("OCR1".utf8); aad.append(track.rawValue); aad.append(idBytes); aad.append(be64(counter))
        guard let box = try? AES.GCM.SealedBox(nonce: AES.GCM.Nonce(data: nonceBytes), ciphertext: body.dropLast(16),
                                               tag: body.suffix(16)),
              let plain = try? AES.GCM.open(box, using: key, authenticating: aad), let kind = plain.first
        else { return broken("wrong key or changed frame") }
        let payload = plain.dropFirst()
        switch kind {
        case 0 where counter == 0:
            details = (try? JSONSerialization.jsonObject(with: Data(payload))) ?? NSNull()
        case 1 where counter > 0 && payload.count >= 8 && (payload.count - 8) % 2 == 0:
            let start = Data(payload.prefix(8)).withUnsafeBytes { $0.loadUnaligned(as: UInt64.self).bigEndian }
            let pcm: [Int16] = Data(payload.dropFirst(8)).withUnsafeBytes { raw in
                (0 ..< raw.count / 2).map { Int16(littleEndian: raw.loadUnaligned(fromByteOffset: $0 * 2, as: Int16.self)) }
            }
            for s in pcm { if (s >= 0) != (last >= 0) { crossings += 1 }; last = s }
            if let n = next, start > n + UInt64(sampleRate / 2) {
                gaps.append([Double(n) / sampleRate, Double(start) / sampleRate])
            }
            next = max(next ?? 0, start + UInt64(pcm.count))
            frames += 1; samples += UInt64(pcm.count)
            onAudio?(start, pcm)
        case 2 where counter > 0 && payload.count == 16:
            let f = Data(payload.prefix(8)).withUnsafeBytes { $0.loadUnaligned(as: UInt64.self).bigEndian }
            let s = Data(payload.suffix(8)).withUnsafeBytes { $0.loadUnaligned(as: UInt64.self).bigEndian }
            guard f == frames, s == samples else { return broken("totals") }
            guard at + 16 + n == data.endIndex else { return broken("data after the end") }
            return result("complete")
        default:
            return broken("frame kind")
        }
        counter += 1
        at += 16 + n
    }
    return cut()
    func cut() -> [String: Any] { result("cut off") }
    func result(_ st: String) -> [String: Any] {
        let secs = Double(samples) / sampleRate
        return ["state": st, "track": track == .me ? "me" : "others", "frames": frames, "samples": samples,
                "seconds": secs, "hz": secs > 0 ? Double(crossings) / 2 / secs : 0, "details": details, "gaps": gaps,
                "recording": UUID(uuid: idBytes.withUnsafeBytes { $0.loadUnaligned(as: uuid_t.self) }).uuidString.lowercased()]
    }
}

func readRecording(_ folder: URL, keys: KeyStore) -> [String: Any] {
    let id = folder.lastPathComponent
    guard let key = keys.get(id) else { return ["state": "broken", "why": "no key"] }
    var out: [String: Any] = [:]
    for t in [Track.me, .others] {
        var r = readTrack(folder.appendingPathComponent(t.file), key: key, expect: t)
        if let rid = r["recording"] as? String, rid != id { r = ["state": "broken", "why": "another recording"] }
        out[t == .me ? "me" : "others"] = r
    }
    return out
}
