import Foundation

/// Pure rules of the hands-busy New topic screen (tile order, opening state, the 1-second minimum).
enum NewTopicRules {
    static let lastWorkspaceKey = "newTopicLastWorkspace"
    static let autoMicKey = "autoMic"
    /// A memo shorter than this is not sent (same limit as the Composer).
    static let minimumSeconds: TimeInterval = 1
    static let maxTiles = 3

    /// The workspace that is picked when the screen opens: last used, else the one that opened the screen, else the first.
    static func initialSelection(ids: [String], lastUsed: String?, opener: String?) -> String? {
        if let lastUsed, ids.contains(lastUsed) { return lastUsed }
        if let opener, ids.contains(opener) { return opener }
        return ids.first
    }

    /// Up to three workspace tiles, the preferred one first (then the rest in their own order). The picked one always shows.
    static func tiles(ids: [String], preferred: String?, selected: String?) -> [String] {
        var ordered = ids
        if let preferred, let i = ordered.firstIndex(of: preferred) { ordered.remove(at: i); ordered.insert(preferred, at: 0) }
        var shown = Array(ordered.prefix(maxTiles))
        if let selected, ids.contains(selected), !shown.contains(selected) { shown[shown.count - 1] = selected }
        return shown
    }

    /// The "More" tile only shows when not every workspace has its own tile.
    static func hasMore(count: Int) -> Bool { count > maxTiles }

    /// With the "Start recording right away" setting on, the screen opens in the recording state (needs a workspace to send to).
    static func opensRecording(autoMic: Bool, hasWorkspace: Bool) -> Bool { autoMic && hasWorkspace }

    static func longEnough(_ segments: [VoiceSegment]) -> Bool { segments.reduce(0) { $0 + $1.duration } >= minimumSeconds }

    /// mm:ss for the big timer.
    static func clock(_ seconds: TimeInterval) -> String {
        let s = max(0, Int(seconds)); return String(format: "%02d:%02d", s / 60, s % 60)
    }
}

extension AppModel {
    /// Sends recorded segments as voice memos in order (the same steps the Composer uses); each file is removed once queued.
    @discardableResult
    func sendVoiceSegments(_ segments: [VoiceSegment], to target: SendTarget) async throws -> Int {
        var sent = 0
        for segment in segments {
            let draft = await voiceDraft(for: segment)
            try await send(MessageDraft(voice: draft, replyTo: nil), to: target)
            try? FileManager.default.removeItem(at: segment.url); sent += 1
        }
        return sent
    }
}
