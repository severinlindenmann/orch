import SwiftUI
import UIKit

/// New topic, voice first: record, see the words written down, then Send, Record more or Edit.
/// The recording and transcribing steps live here; the parent screen only picks the workspace and opens the topic afterwards.
struct NewTopicVoiceView: View {
    let workspace: WorkspaceSummary
    let name: String
    /// Cancel on any screen: everything recorded is discarded.
    let onCancel: () -> Void
    /// The microphone did not start, or the recording was too short: back to the start with this message.
    let onFailed: (String) -> Void
    /// The memo is sent (or queued): the parent remembers the workspace and opens the topic.
    let onSent: () -> Void

    @Environment(AppModel.self) private var model
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var flow = NewTopicVoiceFlow()
    @State private var recorder: VoiceRecorder?
    @State private var starting = false
    @State private var hint = false
    @State private var error: String?
    @State private var success = 0
    /// Transcribed segments of earlier takes, and the segments of the take being written down.
    @State private var ready: [DraftVoice] = []
    @State private var pending: [VoiceSegment] = []
    @State private var textSent = false
    @State private var finished = false
    @FocusState private var editFocus: Bool

    var body: some View {
        VStack(spacing: 20) {
            card
            switch flow.phase {
            case .recording: recordingBody
            case .transcribing: transcribingBody
            case .review, .editing, .sending: reviewBody
            case .failed: failedBody
            }
        }
        .padding(16)
        .sensoryFeedback(.success, trigger: success)
        .task { await startRecording() }
        .onDisappear { if !finished { discardAll() } }
    }

    private var card: some View {
        HStack(spacing: 12) {
            WorkspaceBadge(name: name, icon: workspace.workspace.icon, color: workspace.workspace.color, size: 44)
            VStack(alignment: .leading, spacing: 2) {
                Text(name).themeFont(17, .semibold); Text("new topic").themeFont(13).foregroundStyle(Theme.muted)
            }
            Spacer()
        }.padding(12).background(Theme.surface2, in: RoundedRectangle(cornerRadius: Theme.Radius.m, style: .continuous))
            .accessibilityElement(children: .combine)
    }

    // MARK: Recording

    private var recordingBody: some View {
        VStack(spacing: 20) {
            Spacer(minLength: 0)
            TimelineView(.periodic(from: .now, by: 0.25)) { _ in
                let seconds = (recorder?.elapsed ?? 0) + (recorder?.finished.reduce(0) { $0 + $1.duration } ?? 0)
                Text(NewTopicRules.clock(seconds)).font(.system(size: 64, weight: .semibold).monospacedDigit())
                    .accessibilityLabel("Recording, \(Int(seconds)) seconds")
            }
            HStack(spacing: 8) {
                Circle().fill(Theme.danger).frame(width: 12, height: 12)
                Text(starting ? "Starting…" : "Recording").themeFont(17, .semibold)
            }.accessibilityElement(children: .combine)
            waves
            if hint { Text("Too short. Hold on a little longer.").themeFont(14).foregroundStyle(Theme.warn) }
            if let error { Text(error).themeFont(14).foregroundStyle(Theme.danger).multilineTextAlignment(.center) }
            Spacer(minLength: 0)
            Button { Task { await done() } } label: {
                Image(systemName: "checkmark").font(.system(size: 36, weight: .bold)).foregroundStyle(Theme.onBrand)
                    .frame(width: 96, height: 96).background(Theme.brand, in: Circle())
            }.buttonStyle(PressStyle()).disabled(starting).accessibilityLabel("Done").accessibilityIdentifier("nt-done")
            cancelButton.padding(.top, 28)
        }
    }
    private var waves: some View {
        HStack(alignment: .center, spacing: 5) {
            ForEach(Array((recorder?.levels ?? [Double](repeating: 0, count: VoiceRecorder.barCount)).enumerated()), id: \.offset) { _, level in
                Capsule().fill(Theme.brand).frame(width: 6, height: 8 + 44 * level)
            }
        }.frame(height: 56).animation(reduceMotion ? nil : .linear(duration: 0.08), value: recorder?.levels).accessibilityHidden(true)
    }
    private var cancelButton: some View {
        Button { discardAll(); onCancel() } label: {
            Text("Cancel").themeFont(17, .semibold).frame(maxWidth: .infinity, minHeight: 60)
                .background(Theme.surface3, in: RoundedRectangle(cornerRadius: Theme.Radius.m, style: .continuous))
        }.buttonStyle(PressStyle()).foregroundStyle(Theme.text).disabled(flow.phase == .sending).accessibilityIdentifier("nt-cancel")
    }

    // MARK: Writing it down

    private var transcribingBody: some View {
        VStack(spacing: 20) {
            Spacer()
            ProgressView().controlSize(.large).scaleEffect(1.6).tint(Theme.brand).padding(.bottom, 12)
            Text("Writing it down…").themeFont(22, .semibold)
            Spacer()
        }.frame(maxWidth: .infinity).accessibilityElement(children: .combine).accessibilityIdentifier("nt-transcribing")
    }

    private var failedBody: some View {
        VStack(spacing: 16) {
            Spacer()
            Text("Couldn't write it down.").themeFont(22, .semibold).multilineTextAlignment(.center)
            if let error { Text(error).themeFont(14).foregroundStyle(Theme.danger).multilineTextAlignment(.center) }
            Spacer()
            bigButton("Send as voice memo", primary: true, height: 76, id: "nt-send-voice-only") { Task { await send(voiceOnly: true) } }
            bigButton("Try again", primary: false, height: 60, id: "nt-retry") { flow.retry(); Task { await transcribePending() } }
            cancelButton.padding(.top, 8)
        }
    }

    // MARK: Review

    private var reviewBody: some View {
        let busy = flow.phase == .sending
        return VStack(spacing: 16) {
            if flow.phase == .editing {
                TextEditor(text: Binding(get: { flow.transcript }, set: { flow.setEdited($0) }))
                    .themeFont(22).scrollContentBackground(.hidden).focused($editFocus).padding(12)
                    .background(Theme.surface2, in: RoundedRectangle(cornerRadius: Theme.Radius.m, style: .continuous))
                    .accessibilityLabel("Your words").accessibilityIdentifier("nt-edit-field")
                    .task { editFocus = true }
            } else {
                ScrollView {
                    Text(flow.transcript).themeFont(22).frame(maxWidth: .infinity, alignment: .leading).textSelection(.enabled)
                        .accessibilityIdentifier("nt-transcript")
                }.frame(maxHeight: .infinity)
            }
            if let error { Text(error).themeFont(14).foregroundStyle(Theme.danger).multilineTextAlignment(.center) }
            bigButton(busy ? "Sending…" : "Send", primary: true, height: 76, id: "nt-send") { Task { await send(voiceOnly: false) } }
                .disabled(busy || !flow.canSend)
            if flow.phase != .editing {
                bigButton("Record more", primary: false, height: 60, id: "nt-record-more") { Task { await recordMore() } }.disabled(busy)
                bigButton("Edit", primary: false, height: 60, id: "nt-edit") { flow.edit() }.disabled(busy)
            }
            Button { discardAll(); onCancel() } label: {
                Text("Cancel").themeFont(15, .semibold).foregroundStyle(Theme.muted).frame(minWidth: 120, minHeight: 44).contentShape(Rectangle())
            }.buttonStyle(PressStyle()).disabled(busy).accessibilityIdentifier("nt-cancel")
        }
    }

    private func bigButton(_ title: String, primary: Bool, height: CGFloat, id: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Text(title).themeFont(primary ? 20 : 17, .semibold).frame(maxWidth: .infinity, minHeight: height)
                .background(primary ? Theme.brand : Theme.surface3, in: RoundedRectangle(cornerRadius: Theme.Radius.m, style: .continuous))
                .foregroundStyle(primary ? Theme.onBrand : Theme.text)
        }.buttonStyle(PressStyle()).accessibilityIdentifier(id)
    }

    // MARK: Steps

    private func startRecording() async {
        guard recorder == nil || recorder?.isRecording == false, !starting else { return }
        error = nil; hint = false; starting = true
        let r = model.makeVoiceRecorder(); recorder = r
        do { try await r.start() }
        catch {
            let message = r.error ?? "Could not start the microphone."
            r.cancel(); recorder = nil; starting = false
            if ready.isEmpty { finished = true; onFailed(message) } else { self.error = message; flow.discardTake() }
            return
        }
        starting = false
    }
    private func recordMore() async {
        flow.recordMore(); await startRecording()
    }
    /// Done: stop the recorder and write the words down.
    private func done() async {
        guard let recorder else { return }
        let segments = recorder.stop()
        self.recorder = nil
        guard NewTopicRules.longEnough(segments) else {
            for s in segments { try? FileManager.default.removeItem(at: s.url) }
            if ready.isEmpty { finished = true; onFailed("Too short. Hold on a little longer.") }
            else { hint = true; flow.discardTake() }
            return
        }
        pending = segments; flow.done()
        await transcribePending()
    }
    private func transcribePending() async {
        error = nil
        var texts: [String] = [], drafts: [DraftVoice] = []
        for segment in pending {
            let d = await model.voiceDraft(for: segment)
            drafts.append(d); texts.append(d.transcript)
        }
        if flow.phase != .transcribing { return }
        flow.transcribed(texts)
        if flow.phase != .failed { ready += drafts; pending = [] }
    }

    private func send(voiceOnly: Bool) async {
        let target = SendTarget.newTopic(workspace: workspace.id)
        flow.sending(); error = nil
        // Failed writing-down: the older takes keep their words, the take that failed goes without.
        var drafts = ready + (voiceOnly ? pending.map { DraftVoice(url: $0.url, duration: $0.duration, transcript: "", lang: "", langSource: .detected) } : [])
        if !voiceOnly {
            let texts = textSent ? [String](repeating: "", count: drafts.count) : NewTopicVoiceFlow.transcripts(text: flow.transcript, segmentCount: drafts.count, voiceOnly: false)
            for i in drafts.indices { drafts[i].transcript = texts[i] }
        }
        for d in drafts {
            do {
                try await model.send(MessageDraft(voice: d, replyTo: nil), to: target)
                try? FileManager.default.removeItem(at: d.url)
                if !d.transcript.isEmpty { textSent = true }
                ready.removeAll { $0.url == d.url }
                pending.removeAll { $0.url == d.url }
            } catch {
                self.error = error.localizedDescription; flow.sendFailed(); return
            }
        }
        finished = true; success += 1
        UIAccessibility.post(notification: .announcement, argument: "Sent to \(name)")
        onSent()
    }

    /// Drops the recording and every file of it (Cancel, or the screen closed).
    private func discardAll() {
        recorder?.cancel(); recorder = nil
        for d in ready { try? FileManager.default.removeItem(at: d.url) }
        for s in pending { try? FileManager.default.removeItem(at: s.url) }
        ready = []; pending = []
    }
}
