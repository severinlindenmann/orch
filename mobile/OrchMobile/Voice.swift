import AVFoundation
import Foundation
import Observation
import Speech

/// Voice to text. Tap the mic: record (AAC m4a, 16 kHz mono) with a live level meter; tap again: the file goes to the relay
/// (`POST /v1/phone/transcribe`) and the text lands in `transcript` for the user to edit. If the relay has no transcription
/// (503 transcription_off) or cannot be reached, the Speech framework transcribes the same file on this phone.
/// Modes: `live` real microphone, `scripted` fake recorder (UI tests, mock relay), `file` a given audio file stands in for the mic.
@MainActor @Observable
final class VoiceInput {
    enum Mode: Equatable { case live, scripted, file(URL) }
    typealias Transcribe = @Sendable (Data) async throws -> String
    typealias OnDevice = @Sendable (URL) async throws -> String

    static let barCount = 12
    static let maxSeconds = 120

    private(set) var isRecording = false
    private(set) var isTranscribing = false
    private(set) var transcript = ""
    private(set) var error: String?
    private(set) var levels = [Double](repeating: 0, count: VoiceInput.barCount)   // 0...1, newest last
    private(set) var usedOnDevice = false
    let mode: Mode

    private let transcribe: Transcribe
    private let onDevice: OnDevice
    private var recorder: AVAudioRecorder?
    private var meter: Task<Void, Never>?
    private var job: Task<Void, Never>?
    private var fileURL: URL?
    private var prefix = ""

    init(mode: Mode, transcribe: @escaping Transcribe, onDevice: @escaping OnDevice = VoiceInput.speechOnDevice) {
        self.mode = mode; self.transcribe = transcribe; self.onDevice = onDevice
    }

    /// Relay without transcription or not reachable: use this phone instead.
    nonisolated static func shouldUseOnDevice(_ error: Error) -> Bool {
        switch error as? RelayError {
        case .api(let status, let code, _): return status == 503 && code == "transcription_off"
        case .network: return true
        default: return false
        }
    }

    nonisolated static func message(for error: Error) -> String {
        if case .api(let status, _, _)? = error as? RelayError {
            if status == 429 { return "Too many recordings in a row. Wait a moment and try again." }
            if status == 413 { return "That recording is too long. Keep it under 2 minutes." }
        }
        return "Couldn't transcribe, try again."
    }

    /// Tap the mic: start, tap again: stop and transcribe. `await` returns when recording has started, or when the text is ready.
    func toggle(current: String) async {
        if isRecording { await finish(); return }
        guard !isTranscribing else { return }
        error = nil; usedOnDevice = false
        prefix = current.isEmpty ? "" : current + " "
        transcript = current
        await start()
    }

    /// Leaving the screen: drop the recording and any running upload.
    func stop() {
        job?.cancel(); job = nil
        stopRecorder()
        isTranscribing = false
    }

    // MARK: Recording

    private func start() async {
        switch mode {
        case .scripted:
            fileURL = nil
            begin()
        case .file(let url):
            fileURL = url
            begin()
        case .live:
            guard await AVAudioApplication.requestRecordPermission() else {
                error = "Allow the microphone in Settings to dictate."; return
            }
            let url = FileManager.default.temporaryDirectory.appendingPathComponent("orch-voice-\(UUID().uuidString).m4a")
            do {
                let session = AVAudioSession.sharedInstance()
                try session.setCategory(.record, mode: .default, options: [])
                try session.setActive(true)
                let r = try AVAudioRecorder(url: url, settings: [
                    AVFormatIDKey: kAudioFormatMPEG4AAC, AVSampleRateKey: 16000, AVNumberOfChannelsKey: 1,
                    AVEncoderBitRateKey: 24000, AVEncoderAudioQualityKey: AVAudioQuality.medium.rawValue])
                r.isMeteringEnabled = true
                guard r.record() else { throw RelayError.network("record") }
                recorder = r; fileURL = url
                begin()
            } catch {
                self.error = "Could not start the microphone."
                stopRecorder()
            }
        }
    }

    private func begin() {
        isRecording = true
        levels = [Double](repeating: 0, count: Self.barCount)
        meter = Task { [weak self] in
            var ticks = 0
            while !Task.isCancelled {
                try? await Task.sleep(for: .milliseconds(80))
                if Task.isCancelled { return }
                guard let self else { return }
                self.push(self.currentLevel(tick: ticks))
                ticks += 1
                if ticks >= Self.maxSeconds * 12 { await self.finish(); return }
            }
        }
    }

    private func currentLevel(tick: Int) -> Double {
        if let r = recorder {
            r.updateMeters()
            return max(0, min(1, (Double(r.averagePower(forChannel: 0)) + 50) / 50))
        }
        return 0.35 + 0.35 * abs(sin(Double(tick) * 0.7)) + 0.1 * abs(sin(Double(tick) * 2.3))   // fake recorder
    }

    private func push(_ level: Double) { levels.removeFirst(); levels.append(level) }

    private func stopRecorder() {
        meter?.cancel(); meter = nil
        recorder?.stop(); recorder = nil
        isRecording = false
        levels = [Double](repeating: 0, count: Self.barCount)
        if mode == .live { try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation) }
    }

    // MARK: Transcribing

    private func finish() async {
        guard isRecording else { return }
        let file = fileURL
        let isTemp = mode == .live
        stopRecorder()
        isTranscribing = true
        let work = Task { [weak self] in await self?.run(file: file); return }
        job = work
        await work.value
        if isTemp, let file { try? FileManager.default.removeItem(at: file) }
    }

    private func run(file: URL?) async {
        defer { isTranscribing = false }
        let audio = file.flatMap { try? Data(contentsOf: $0) } ?? Data("scripted-audio".utf8)
        do {
            let text = try await transcribe(audio)
            if Task.isCancelled { return }
            transcript = prefix + text
        } catch {
            if Task.isCancelled { return }
            guard Self.shouldUseOnDevice(error), let file else { self.error = Self.message(for: error); return }
            do {
                usedOnDevice = true
                let text = try await onDevice(file)
                if Task.isCancelled { return }
                transcript = prefix + text
            } catch { self.error = Self.message(for: error) }
        }
    }

    /// The Speech framework, on this phone, on the recorded file.
    nonisolated static func speechOnDevice(_ url: URL) async throws -> String {
        let ok = await withCheckedContinuation { (c: CheckedContinuation<Bool, Never>) in
            SFSpeechRecognizer.requestAuthorization { c.resume(returning: $0 == .authorized) }
        }
        guard ok, let recognizer = SFSpeechRecognizer(), recognizer.isAvailable else { throw RelayError.network("speech unavailable") }
        return try await speechOnDevice(url, recognizer: recognizer)
    }

    nonisolated static func speechOnDevice(_ url: URL, recognizer: SFSpeechRecognizer) async throws -> String {
        let req = SFSpeechURLRecognitionRequest(url: url)
        if recognizer.supportsOnDeviceRecognition { req.requiresOnDeviceRecognition = true }
        return try await withCheckedThrowingContinuation { (c: CheckedContinuation<String, Error>) in
            let done = Done()
            recognizer.recognitionTask(with: req) { result, err in
                if let err { if done.once() { c.resume(throwing: err) }; return }
                if let result, result.isFinal, done.once() { c.resume(returning: result.bestTranscription.formattedString) }
            }
        }
    }

    private final class Done: @unchecked Sendable {
        private let lock = NSLock(); private var fired = false
        func once() -> Bool { lock.lock(); defer { lock.unlock() }; if fired { return false }; fired = true; return true }
    }
}

// MARK: Voice memos (v3)

/// One recorded file of a voice memo.
struct VoiceSegment: Equatable, Sendable {
    let url: URL
    let duration: TimeInterval
}

/// Records a voice memo: AAC m4a, metering levels for the waveform, and an automatic split every `maxSegmentSeconds` (2 minutes, the
/// relay's transcription limit): at the cap the file is closed and a new one starts without a gap, so `stop()` returns several
/// segments for a long recording (each becomes its own message, in order).
@MainActor @Observable
final class VoiceRecorder {
    enum Mode: Equatable { case live, scripted }
    static let barCount = 12
    static let defaultMaxSegmentSeconds: TimeInterval = 120

    private(set) var isRecording = false
    private(set) var levels = [Double](repeating: 0, count: VoiceRecorder.barCount)    // 0...1, newest last
    /// Seconds recorded in the current segment.
    private(set) var elapsed: TimeInterval = 0
    /// Segments already closed by the cap (the one being recorded is not in the list).
    private(set) var finished: [VoiceSegment] = []
    private(set) var error: String?
    let mode: Mode
    let maxSegmentSeconds: TimeInterval
    private let directory: URL
    private var recorder: AVAudioRecorder?
    private var currentURL: URL?
    private var segmentStart = Date()
    private var meter: Task<Void, Never>?

    init(mode: Mode, maxSegmentSeconds: TimeInterval = VoiceRecorder.defaultMaxSegmentSeconds, directory: URL = FileManager.default.temporaryDirectory) {
        self.mode = mode; self.maxSegmentSeconds = maxSegmentSeconds; self.directory = directory
    }

    /// Starts recording. Throws when the microphone is not allowed or cannot start.
    func start() async throws {
        guard !isRecording else { return }
        error = nil; finished = []; elapsed = 0
        if mode == .live {
            guard await AVAudioApplication.requestRecordPermission() else { error = "Allow the microphone in Settings to record."; throw RelayError.network("mic") }
            do { try AudioSession.recording() } catch { self.error = "Could not start the microphone."; throw error }
        }
        try beginSegment()
        isRecording = true
        meter = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(for: .milliseconds(80))
                guard let self, !Task.isCancelled else { return }
                self.tick()
            }
        }
    }

    /// Stops and returns every segment in order (the last one included). Safe when nothing is recording.
    @discardableResult
    func stop() -> [VoiceSegment] {
        guard isRecording else { return finished }
        meter?.cancel(); meter = nil
        endSegment()
        isRecording = false; elapsed = 0
        levels = [Double](repeating: 0, count: Self.barCount)
        if mode == .live { AudioSession.playback() }
        return finished
    }

    /// Drops everything recorded so far (files deleted).
    func cancel() {
        let segs = stop()
        for s in segs { try? FileManager.default.removeItem(at: s.url) }
        finished = []
    }

    private func beginSegment() throws {
        let url = directory.appendingPathComponent("orch-voice-\(UUID().uuidString).m4a")
        switch mode {
        case .scripted:
            try Data("scripted-audio".utf8).write(to: url)
        case .live:
            let r = try AVAudioRecorder(url: url, settings: [AVFormatIDKey: kAudioFormatMPEG4AAC, AVSampleRateKey: 16000, AVNumberOfChannelsKey: 1,
                                                             AVEncoderBitRateKey: 32000, AVEncoderAudioQualityKey: AVAudioQuality.medium.rawValue])
            r.isMeteringEnabled = true
            guard r.record() else { throw RelayError.network("record") }
            recorder = r
        }
        currentURL = url; segmentStart = Date(); elapsed = 0
    }

    private func endSegment() {
        guard let url = currentURL else { return }
        let seconds = recorder?.currentTime ?? Date().timeIntervalSince(segmentStart)
        recorder?.stop(); recorder = nil
        finished.append(VoiceSegment(url: url, duration: seconds)); currentURL = nil
    }

    private func tick() {
        elapsed = recorder?.currentTime ?? Date().timeIntervalSince(segmentStart)
        var level = 0.35 + 0.35 * abs(sin(elapsed * 9)) + 0.1 * abs(sin(elapsed * 28))      // scripted
        if let r = recorder { r.updateMeters(); level = max(0, min(1, (Double(r.averagePower(forChannel: 0)) + 50) / 50)) }
        levels.removeFirst(); levels.append(level)
        if elapsed >= maxSegmentSeconds {                  // the cap: close this file, start the next one
            endSegment()
            do { try beginSegment() } catch { self.error = "The recording stopped."; isRecording = false; meter?.cancel(); meter = nil }
        }
    }
}

/// The result of turning a voice memo into text.
struct VoiceTranscription: Equatable, Sendable {
    var text: String
    var lang: String
    var langSource: VoiceMemo.LangSource
    var usedOnDevice: Bool
    /// Nothing could be transcribed (the memo is still sent, with an empty transcript).
    var failed: Bool
}

/// Relay transcription first (`swiss_german` -> `de-CH`; a corrected language wins), the phone's own speech recognition when the relay
/// has none or cannot be reached.
struct VoiceTranscriber: Sendable {
    typealias Relay = @Sendable (Data, String?) async throws -> Transcript
    typealias OnDevice = @Sendable (URL, String) async throws -> String
    let relay: Relay
    let onDevice: OnDevice
    var deviceLanguage: String = Locale.current.language.languageCode?.identifier ?? "en"

    init(relay: @escaping Relay, onDevice: @escaping OnDevice = OnDeviceSpeech.transcribe, deviceLanguage: String? = nil) {
        self.relay = relay; self.onDevice = onDevice
        if let deviceLanguage { self.deviceLanguage = deviceLanguage }
    }

    func transcribe(file: URL, swissGerman: Bool, corrected: String? = nil) async -> VoiceTranscription {
        let requested: String? = corrected ?? (swissGerman ? "de-CH" : nil)
        let source: VoiceMemo.LangSource = corrected != nil ? .corrected : (swissGerman ? .setting : .detected)
        do {
            let audio = try Data(contentsOf: file)
            let r = try await relay(audio, requested)
            return VoiceTranscription(text: r.text, lang: requested ?? r.language ?? deviceLanguage, langSource: source, usedOnDevice: false, failed: false)
        } catch where VoiceInput.shouldUseOnDevice(error) {
            let lang = requested ?? deviceLanguage
            do {
                let text = try await onDevice(file, lang)
                return VoiceTranscription(text: text, lang: lang, langSource: source, usedOnDevice: true, failed: false)
            } catch { return VoiceTranscription(text: "", lang: lang, langSource: source, usedOnDevice: true, failed: true) }
        } catch { return VoiceTranscription(text: "", lang: requested ?? deviceLanguage, langSource: source, usedOnDevice: false, failed: true) }
    }
}

/// On-device speech recognition: SpeechAnalyzer (iOS 26+) where the language is available, else SFSpeechRecognizer.
enum OnDeviceSpeech {
    static func transcribe(_ url: URL, language: String) async throws -> String {
        if #available(iOS 26.0, *), let text = try? await analyzer(url, language: language), !text.isEmpty { return text }
        return try await legacy(url, language: language)
    }

    @available(iOS 26.0, *)
    private static func analyzer(_ url: URL, language: String) async throws -> String {
        guard SpeechTranscriber.isAvailable, let locale = await SpeechTranscriber.supportedLocale(equivalentTo: Locale(identifier: language)) else {
            throw RelayError.network("speech unavailable")
        }
        let transcriber = SpeechTranscriber(locale: locale, preset: .transcription)
        if let request = try await AssetInventory.assetInstallationRequest(supporting: [transcriber]) { try await request.downloadAndInstall() }
        let analyzer = SpeechAnalyzer(modules: [transcriber])
        let collect = Task { () -> String in
            var s = ""
            for try await r in transcriber.results { s += String(r.text.characters) }
            return s
        }
        let file = try AVAudioFile(forReading: url)
        if let last = try await analyzer.analyzeSequence(from: file) { try await analyzer.finalizeAndFinish(through: last) } else { await analyzer.cancelAndFinishNow() }
        return try await collect.value.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private static func legacy(_ url: URL, language: String) async throws -> String {
        let ok = await withCheckedContinuation { (c: CheckedContinuation<Bool, Never>) in
            SFSpeechRecognizer.requestAuthorization { c.resume(returning: $0 == .authorized) }
        }
        guard ok, let recognizer = SFSpeechRecognizer(locale: Locale(identifier: language)) ?? SFSpeechRecognizer(), recognizer.isAvailable else { throw RelayError.network("speech unavailable") }
        return try await VoiceInput.speechOnDevice(url, recognizer: recognizer)
    }
}
