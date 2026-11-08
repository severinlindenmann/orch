import AVFoundation
import Foundation
import MediaPlayer
import Observation

/// What GET /v1/phone/speech speaks for a text (relay-api.md, Speech). The phone needs it for its own voice when the relay has
/// none (402 cap reached, 503 off, 502 failed): the same words, so both voices say the same thing.
enum SpokenText {
    static let maxChars = 900

    static func make(text: String, summary: String? = nil) -> String {
        var s = (summary?.isEmpty == false ? summary! : text)
        s = s.replacingOccurrences(of: "https?://\\S+", with: "link", options: .regularExpression)
        s.removeAll { "*`#".contains($0) }
        s = s.replacingOccurrences(of: "\\s+", with: " ", options: .regularExpression).trimmingCharacters(in: .whitespaces)
        let chars = Array(s)
        guard chars.count > maxChars else { return s }
        let head = Array(chars.prefix(maxChars + 1))                   // one more, so a space right after the 900th character counts
        var cut: Int?
        for i in stride(from: min(maxChars, head.count) - 1, through: 0, by: -1) where ".!?".contains(head[i]) && i + 1 < head.count && head[i + 1] == " " { cut = i + 1; break }
        if cut == nil, let sp = head.prefix(maxChars).lastIndex(of: " ") { cut = sp }
        return String(chars.prefix(cut ?? maxChars)).trimmingCharacters(in: .whitespaces)
    }
}

/// The audio session. `.playback` for read-aloud (sound with the silent switch on, lock-screen controls); `.playAndRecord` only
/// while recording a voice memo.
enum AudioSession {
    static func playback() { try? AVAudioSession.sharedInstance().setCategory(.playback, mode: .spokenAudio, options: []); try? AVAudioSession.sharedInstance().setActive(true) }
    static func recording() throws {
        let s = AVAudioSession.sharedInstance()
        try s.setCategory(.playAndRecord, mode: .default, options: [.defaultToSpeaker, .allowBluetooth])
        try s.setActive(true)
    }
    static func idle() { try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation) }
}

@MainActor protocol AudioPlaying: AnyObject {
    func start(data: Data, rate: Float, onFinish: @escaping @MainActor () -> Void) throws
    func pause()
    func resume()
    func stop()
    func setRate(_ rate: Float)
    var currentTime: TimeInterval { get }
    var duration: TimeInterval { get }
    func seek(to time: TimeInterval)
}
extension AudioPlaying { func seek(to time: TimeInterval) {} }
@MainActor protocol Synthesizing: AnyObject {
    func speak(_ text: String, lang: String, rate: Float, onFinish: @escaping @MainActor () -> Void)
    func stop()
}

@MainActor final class AVPlayerBackend: NSObject, AudioPlaying, @preconcurrency AVAudioPlayerDelegate {
    private var player: AVAudioPlayer?
    private var finish: (@MainActor () -> Void)?
    func start(data: Data, rate: Float, onFinish: @escaping @MainActor () -> Void) throws {
        let p = try AVAudioPlayer(data: data)
        p.enableRate = true; p.rate = rate; p.delegate = self
        player = p; finish = onFinish
        guard p.play() else { throw RelayError.network("play") }
    }
    func pause() { player?.pause() }
    func resume() { player?.play() }
    func stop() { player?.stop(); player = nil }
    func setRate(_ rate: Float) { player?.rate = rate }
    var currentTime: TimeInterval { player?.currentTime ?? 0 }
    var duration: TimeInterval { player?.duration ?? 0 }
    func seek(to time: TimeInterval) { player?.currentTime = max(0, min(time, player?.duration ?? 0)) }
    func audioPlayerDidFinishPlaying(_ p: AVAudioPlayer, successfully: Bool) { let f = finish; Task { @MainActor in f?() } }
}

@MainActor final class AVSynthesizerBackend: NSObject, Synthesizing, @preconcurrency AVSpeechSynthesizerDelegate {
    private let synth = AVSpeechSynthesizer()
    private var finish: (@MainActor () -> Void)?
    override init() { super.init(); synth.delegate = self }
    func speak(_ text: String, lang: String, rate: Float, onFinish: @escaping @MainActor () -> Void) {
        let u = AVSpeechUtterance(string: text)
        u.voice = AVSpeechSynthesisVoice(language: lang == "de" ? "de-DE" : "en-US")
        u.rate = AVSpeechUtteranceDefaultSpeechRate * rate
        finish = onFinish; synth.speak(u)
    }
    func stop() { finish = nil; synth.stopSpeaking(at: .immediate) }
    func speechSynthesizer(_ s: AVSpeechSynthesizer, didFinish u: AVSpeechUtterance) { let f = finish; Task { @MainActor in f?() } }
}

/// One thing to read aloud.
struct SpeechClip: Equatable, Sendable {
    let messageId: String
    let text: String
    let summary: String?
    let lang: String
    /// Shown on the lock screen.
    let title: String
}

/// Read-aloud: fetches `/v1/phone/speech/<id>` (cached on disk, cached audio is free), plays it at 1x / 1.5x / 2x, remembers what was
/// listened to, plays the next clip when one ends, shows Now Playing and remote commands, and falls back to the phone's own voice
/// when the relay answers 402 / 503 / 502.
@MainActor @Observable
final class SpeechPlayer {
    enum State: Equatable { case idle, loading(String), playing(String), paused(String) }
    static let rates: [Double] = [1, 1.5, 2]

    private(set) var state: State = .idle
    private(set) var rate: Double = 1
    private(set) var listened: Set<String>
    /// The current clip was read by the phone's own voice (the relay had none left).
    private(set) var usingPhoneVoice = false
    private(set) var queue: [SpeechClip] = []
    private(set) var current: SpeechClip?
    /// Set when the relay refused with a reason a person should know ("Read-aloud budget used up. Using the phone's voice.").
    private(set) var notice: String?
    /// 0...1 position in the current clip (updated while it plays; 0 for the phone's own voice).
    private(set) var progress: Double = 0
    private var progressTask: Task<Void, Never>?

    typealias Fetch = @Sendable (_ messageId: String, _ lang: String?) async throws -> Data
    private let fetch: Fetch
    private let cacheDir: URL
    private let audio: any AudioPlaying
    private let synth: any Synthesizing
    private let defaults: UserDefaults
    private let systemControls: Bool
    private var job: Task<Void, Never>?
    private var generation = 0
    private var commandTokens: [(MPRemoteCommand, Any)] = []

    init(fetch: @escaping Fetch, cacheDirectory: URL, audio: (any AudioPlaying)? = nil, synth: (any Synthesizing)? = nil,
         defaults: UserDefaults = .standard, systemControls: Bool = true) {
        self.fetch = fetch; self.cacheDir = cacheDirectory; self.defaults = defaults; self.systemControls = systemControls
        self.audio = audio ?? AVPlayerBackend(); self.synth = synth ?? AVSynthesizerBackend()
        listened = Set(defaults.stringArray(forKey: "speechListened") ?? [])
        try? FileManager.default.createDirectory(at: cacheDirectory, withIntermediateDirectories: true)
        if systemControls { registerRemoteCommands() }
    }

    static var defaultCacheDirectory: URL { FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask)[0].appendingPathComponent("speech", isDirectory: true) }

    func isListened(_ messageId: String) -> Bool { listened.contains(messageId) }
    var isActive: Bool { state != .idle }

    // MARK: Controls

    /// Play `clip`; `next` plays one after the other when it ends (auto-next).
    func play(_ clip: SpeechClip, then next: [SpeechClip] = []) {
        stopAll(keepNotice: false)
        queue = next; current = clip
        start(clip)
    }
    func pause() {
        guard case .playing(let id) = state else { return }
        // The phone's own voice cannot resume: pausing it stops it and drops the current clip. The queue is kept, so "next" /
        // a new play() still works; the lock screen entry goes away.
        if usingPhoneVoice { synth.stop(); state = .idle; current = nil; usingPhoneVoice = false; clearNowPlaying(); return }
        audio.pause(); state = .paused(id); updateNowPlaying()
    }
    func resume() {
        guard case .paused(let id) = state else { return }
        audio.resume(); state = .playing(id); updateNowPlaying()
    }
    func toggle() { if case .playing = state { pause() } else { resume() } }
    func stop() { stopAll(keepNotice: false); queue = []; current = nil }
    /// 1x -> 1.5x -> 2x -> 1x. Applies to the clip that is playing.
    func cycleRate() { setRate(Self.rates[((Self.rates.firstIndex(of: rate) ?? 0) + 1) % Self.rates.count]) }
    func setRate(_ r: Double) {
        guard Self.rates.contains(r) else { return }
        rate = r; audio.setRate(Float(r)); updateNowPlaying()
    }
    func skipToNext() { finishCurrent(played: false) }
    /// Scrub the current clip (fraction 0...1). No effect with the phone's own voice.
    func seek(to fraction: Double) {
        guard !usingPhoneVoice, audio.duration > 0 else { return }
        audio.seek(to: audio.duration * max(0, min(1, fraction))); progress = max(0, min(1, fraction)); updateNowPlaying()
    }

    // MARK: Playing

    private func stopAll(keepNotice: Bool) {
        generation += 1; job?.cancel(); job = nil
        audio.stop(); synth.stop()
        state = .idle; usingPhoneVoice = false; progressTask?.cancel(); progress = 0
        if !keepNotice { notice = nil }
        clearNowPlaying()
    }

    private func start(_ clip: SpeechClip) {
        generation += 1; let gen = generation
        state = .loading(clip.messageId); usingPhoneVoice = false
        job = Task { [weak self] in
            guard let self else { return }
            do {
                let data = try await self.audioData(for: clip)
                guard gen == self.generation, !Task.isCancelled else { return }
                AudioSession.playback()
                try self.audio.start(data: data, rate: Float(self.rate)) { [weak self] in self?.ended(gen) }
                self.state = .playing(clip.messageId); self.updateNowPlaying(); self.trackProgress(gen)
            } catch {
                guard gen == self.generation, !Task.isCancelled else { return }
                self.fallBack(clip, because: error, gen)
            }
        }
    }

    /// Cached audio first (free, offline); else the relay.
    static func isValidMessageId(_ id: String) -> Bool { id.range(of: "^m_[a-z0-9]{16}$", options: .regularExpression) != nil }
    static let cacheLimitBytes = 50 * 1024 * 1024

    /// Length of the audio already on disk for this clip (after the first play); nil until then.
    func cachedDuration(for clip: SpeechClip) async -> Double? {
        guard Self.isValidMessageId(clip.messageId), ["de", "en"].contains(clip.lang) else { return nil }
        return await AudioLength.seconds(of: cacheDir.appendingPathComponent("\(clip.messageId)-\(clip.lang).mp3"))
    }

    private func audioData(for clip: SpeechClip) async throws -> Data {
        // The id becomes part of a file name: only the relay's own shape is accepted (no path tricks).
        guard Self.isValidMessageId(clip.messageId), ["de", "en"].contains(clip.lang) else { throw RelayError.api(status: 404, code: "not_found", message: "Nothing to read aloud.") }
        let url = cacheDir.appendingPathComponent("\(clip.messageId)-\(clip.lang).mp3")
        if let d = try? Data(contentsOf: url), !d.isEmpty {
            try? FileManager.default.setAttributes([.modificationDate: Date()], ofItemAtPath: url.path)    // last used, for eviction
            return d
        }
        let d = try await fetch(clip.messageId, clip.lang)
        try? d.write(to: url, options: .atomic)
        Self.evict(cacheDir, limit: Self.cacheLimitBytes, keep: url)
        return d
    }

    /// Least recently used files go first until the folder is at most `limit` bytes. `keep` is never removed.
    nonisolated static func evict(_ dir: URL, limit: Int, keep: URL? = nil) {
        let fm = FileManager.default
        guard let urls = try? fm.contentsOfDirectory(at: dir, includingPropertiesForKeys: [.contentModificationDateKey, .fileSizeKey]) else { return }
        var files = urls.compactMap { u -> (URL, Date, Int)? in
            guard let v = try? u.resourceValues(forKeys: [.contentModificationDateKey, .fileSizeKey]) else { return nil }
            return (u, v.contentModificationDate ?? .distantPast, v.fileSize ?? 0)
        }.sorted { $0.1 < $1.1 }
        var total = files.reduce(0) { $0 + $1.2 }
        while total > limit, !files.isEmpty {
            let f = files.removeFirst()
            if f.0 == keep { continue }
            try? fm.removeItem(at: f.0); total -= f.2
        }
    }

    /// 402 / 503 / 502 (and no network): the phone reads the same words with its own voice. Anything else (404, 401...) just stops.
    nonisolated static func shouldUsePhoneVoice(_ error: Error) -> Bool {
        switch error as? RelayError {
        case .api(let status, _, _)?: return [402, 502, 503].contains(status)
        case .network?: return true
        default: return error is URLError
        }
    }
    nonisolated static func notice(for error: Error) -> String? {
        if case .api(402, _, _)? = error as? RelayError { return "The read-aloud budget is used up. Using this phone's voice." }
        return nil
    }

    private func fallBack(_ clip: SpeechClip, because error: Error, _ gen: Int) {
        guard Self.shouldUsePhoneVoice(error) else { state = .idle; current = nil; queue = []; return }
        notice = Self.notice(for: error); usingPhoneVoice = true
        AudioSession.playback()
        state = .playing(clip.messageId)
        synth.speak(SpokenText.make(text: clip.text, summary: clip.summary), lang: clip.lang, rate: Float(rate)) { [weak self] in self?.ended(gen) }
        updateNowPlaying()
    }

    private func trackProgress(_ gen: Int) {
        progressTask?.cancel()
        progressTask = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(for: .milliseconds(100))
                guard let self, gen == self.generation else { return }
                if case .playing = self.state, self.audio.duration > 0 { self.progress = self.audio.currentTime / self.audio.duration }
            }
        }
    }

    private func ended(_ gen: Int) {
        guard gen == generation else { return }
        finishCurrent(played: true)
    }

    /// The clip ended (or was skipped): mark it listened (if it played to the end) and start the next one.
    private func finishCurrent(played: Bool) {
        if played, let c = current { markListened(c.messageId) }
        job?.cancel(); audio.stop(); synth.stop(); usingPhoneVoice = false
        if queue.isEmpty { state = .idle; current = nil; clearNowPlaying(); AudioSession.idle(); return }
        let next = queue.removeFirst(); current = next
        start(next)
    }

    private func markListened(_ id: String) {
        listened.insert(id)
        defaults.set(Array(listened), forKey: "speechListened")
    }
    /// Sign-out: forget what was listened to and drop cached audio.
    func reset() {
        stop(); listened = []; defaults.removeObject(forKey: "speechListened")
        try? FileManager.default.removeItem(at: cacheDir)
        try? FileManager.default.createDirectory(at: cacheDir, withIntermediateDirectories: true)
    }

    // MARK: Lock screen

    private func updateNowPlaying() {
        guard systemControls, let c = current else { return }
        var info: [String: Any] = [MPMediaItemPropertyTitle: c.title, MPMediaItemPropertyArtist: "orch",
                                   MPNowPlayingInfoPropertyPlaybackRate: state == .paused(c.messageId) ? 0.0 : rate]
        if !usingPhoneVoice { info[MPMediaItemPropertyPlaybackDuration] = audio.duration; info[MPNowPlayingInfoPropertyElapsedPlaybackTime] = audio.currentTime }
        MPNowPlayingInfoCenter.default().nowPlayingInfo = info
    }
    private func clearNowPlaying() { if systemControls { MPNowPlayingInfoCenter.default().nowPlayingInfo = nil } }

    private func registerRemoteCommands() {
        let c = MPRemoteCommandCenter.shared()
        func add(_ cmd: MPRemoteCommand, _ action: @escaping @MainActor (SpeechPlayer) -> Void) {
            let token = cmd.addTarget { [weak self] _ in
                Task { @MainActor in if let self { action(self) } }
                return .success
            }
            commandTokens.append((cmd, token))
        }
        add(c.playCommand) { $0.resume() }
        add(c.pauseCommand) { $0.pause() }
        add(c.togglePlayPauseCommand) { $0.toggle() }
        add(c.nextTrackCommand) { $0.skipToNext() }
        c.changePlaybackRateCommand.supportedPlaybackRates = Self.rates.map { NSNumber(value: $0) }
        let token = c.changePlaybackRateCommand.addTarget { [weak self] e in
            let r = (e as? MPChangePlaybackRateCommandEvent)?.playbackRate ?? 1
            Task { @MainActor in self?.setRate(Double(r)) }
            return .success
        }
        commandTokens.append((c.changePlaybackRateCommand, token))
    }
}
