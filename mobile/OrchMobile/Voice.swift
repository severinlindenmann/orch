import AVFoundation
import Foundation
import Observation
import Speech

/// Voice to text. `live` uses the Speech framework on this phone; `scripted` types a fixed sentence (Simulator, tests, screenshots).
@MainActor @Observable
final class VoiceInput {
    enum Mode { case live, scripted }
    private(set) var isRecording = false
    private(set) var transcript = ""
    private(set) var error: String?
    let mode: Mode

    private var engine: AVAudioEngine?
    private var request: SFSpeechAudioBufferRecognitionRequest?
    private var task: SFSpeechRecognitionTask?
    private var script: Task<Void, Never>?

    init(mode: Mode) { self.mode = mode }

    /// Tap the mic: start, tap again: stop. The transcript stays editable by the caller.
    func toggle(current: String) async {
        if isRecording { stop(); return }
        error = nil
        transcript = current
        switch mode {
        case .scripted: startScripted()
        case .live: await startLive()
        }
    }

    func stop() {
        script?.cancel(); script = nil
        engine?.stop(); engine?.inputNode.removeTap(onBus: 0); engine = nil
        request?.endAudio(); request = nil
        task?.cancel(); task = nil
        isRecording = false
    }

    private func startScripted() {
        isRecording = true
        let words = "Please rename field X to received_date in the ingestion job.".split(separator: " ").map(String.init)
        let prefix = transcript.isEmpty ? "" : transcript + " "
        script = Task { [weak self] in
            var spoken: [String] = []
            for w in words {
                try? await Task.sleep(for: .milliseconds(180))
                if Task.isCancelled { return }
                spoken.append(w)
                self?.transcript = prefix + spoken.joined(separator: " ")
            }
            self?.isRecording = false
        }
    }

    private func startLive() async {
        let speechOK = await withCheckedContinuation { (c: CheckedContinuation<Bool, Never>) in
            SFSpeechRecognizer.requestAuthorization { c.resume(returning: $0 == .authorized) }
        }
        let micOK = await AVAudioApplication.requestRecordPermission()
        guard speechOK, micOK else { error = "Allow the microphone and speech recognition in Settings to dictate."; return }
        guard let recognizer = SFSpeechRecognizer(), recognizer.isAvailable else { error = "Voice input is not available right now."; return }
        do {
            let session = AVAudioSession.sharedInstance()
            try session.setCategory(.record, mode: .measurement, options: .duckOthers)
            try session.setActive(true, options: .notifyOthersOnDeactivation)
            let req = SFSpeechAudioBufferRecognitionRequest()
            req.shouldReportPartialResults = true
            if recognizer.supportsOnDeviceRecognition { req.requiresOnDeviceRecognition = true }
            let engine = AVAudioEngine()
            let input = engine.inputNode
            input.installTap(onBus: 0, bufferSize: 1024, format: input.outputFormat(forBus: 0)) { buffer, _ in req.append(buffer) }
            engine.prepare()
            try engine.start()
            let prefix = transcript.isEmpty ? "" : transcript + " "
            task = recognizer.recognitionTask(with: req) { [weak self] result, err in
                let text = result?.bestTranscription.formattedString
                let finished = result?.isFinal == true || err != nil
                Task { @MainActor in
                    if let text { self?.transcript = prefix + text }
                    if finished { self?.stop() }
                }
            }
            self.engine = engine; self.request = req
            isRecording = true
        } catch {
            self.error = "Could not start the microphone."
            stop()
        }
    }
}
