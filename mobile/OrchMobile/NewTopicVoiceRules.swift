import Foundation

/// Pure state machine of the voice-first New topic flow: recording -> transcribing -> review (-> editing) -> sending.
/// "Record more" goes back to recording and appends the next take's transcript; a failed transcript offers voice-only or retry.
struct NewTopicVoiceFlow: Equatable {
    enum Phase: Equatable { case recording, transcribing, review, editing, sending, failed }
    private(set) var phase = Phase.recording
    /// The transcript of each finished take, in order.
    private(set) var takes: [String] = []
    /// The text the person typed in Edit; nil while the transcript is untouched.
    private(set) var edited: String?
    private(set) var failedOnce = false
    private var before = Phase.review

    /// The text shown on the review screen and sent: the edit when there is one, else all takes in order.
    var transcript: String { edited ?? takes.map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }.filter { !$0.isEmpty }.joined(separator: "\n\n") }
    /// Send is allowed with text, or as a voice memo only after a failure.
    var canSend: Bool { (phase == .review || phase == .editing) && !transcript.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }
    var canSendVoiceOnly: Bool { phase == .failed }

    /// Done pressed: the recorder stopped.
    mutating func done() { if phase == .recording { phase = .transcribing } }
    /// Every part of the new take is transcribed. An empty result counts as a failure.
    mutating func transcribed(_ texts: [String]) {
        guard phase == .transcribing else { return }
        let joined = texts.joined().trimmingCharacters(in: .whitespacesAndNewlines)
        if joined.isEmpty { phase = .failed; failedOnce = true; return }
        let take = texts.map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }.filter { !$0.isEmpty }.joined(separator: "\n\n")
        takes.append(take)
        if let e = edited { edited = e.isEmpty ? take : e + "\n\n" + take }   // a take recorded after an edit joins the edited text
        phase = edited != nil ? .editing : .review
    }
    mutating func transcriptionFailed() { if phase == .transcribing { phase = .failed; failedOnce = true } }
    /// "Try again" on the failure screen: transcribe the same recording once more.
    mutating func retry() { if phase == .failed { phase = .transcribing } }
    /// "Record more": back to recording; the next take is appended.
    mutating func recordMore() { if phase == .review || phase == .editing { phase = .recording } }
    /// The extra take was too short and dropped: back to the review screen with what was there.
    mutating func discardTake() { if phase == .recording, !takes.isEmpty { phase = edited != nil ? .editing : .review } }
    mutating func edit() { if phase == .review { edited = transcript; phase = .editing } }
    mutating func setEdited(_ text: String) { if phase == .editing { edited = text } }
    mutating func sending() { if canSend || canSendVoiceOnly { before = phase; phase = .sending } }
    /// Sending failed: back to where the person was.
    mutating func sendFailed() { if phase == .sending { phase = before } }

    /// The transcript each recorded segment is sent with: the whole text goes with the first segment, the rest carry none
    /// (a voice memo has one transcript, and the edit applies to the whole recording).
    static func transcripts(text: String, segmentCount: Int, voiceOnly: Bool) -> [String] {
        guard segmentCount > 0 else { return [] }
        var out = [String](repeating: "", count: segmentCount)
        if !voiceOnly { out[0] = text }
        return out
    }
}
