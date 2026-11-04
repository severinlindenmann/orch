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
