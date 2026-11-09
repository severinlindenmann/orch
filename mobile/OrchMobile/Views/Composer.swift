import SwiftUI
import AVFoundation

struct ReplyPreview: Equatable {
    let messageId: String
    let title: String
    let quote: String
    var answering: Question? = nil

    static func == (lhs: Self, rhs: Self) -> Bool {
        lhs.messageId == rhs.messageId && lhs.title == rhs.title && lhs.quote == rhs.quote
            && lhs.answering?.id == rhs.answering?.id
    }
}

struct Composer: View {
    let target: SendTarget?
    var placeholder: String
    var note: String?
    var autoFocus: Bool
    @Binding var reply: ReplyPreview?
    var onSent: (() -> Void)?
    /// Accessibility ids of the text field and send button (the New topic screen keeps its older ids).
    var fieldId = "composer-field"
    var sendId = "composer-send"
    var groupKey: GroupKey?
    var unavailableText: String
    @Environment(AppModel.self) private var model
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.dynamicTypeSize) private var typeSize
    @FocusState private var focused: Bool
    @State private var text = ""
    @State private var savedDraft: String?
    @State private var error: String?
    @State private var micError = false
    @State private var attaching = false
    @State private var busy = false
    @State private var success = 0
    @State private var cancellation = 0
    @State private var recorder: VoiceRecorder?
    @State private var segments: [VoiceSegment] = []
    @State private var locked = false
    @State private var holding = false
    @State private var cancelledHold = false
    @State private var starting = false
    @State private var recordingGeneration = UUID()
    @State private var holdTask: Task<Void, Never>?
    @State private var hintTask: Task<Void, Never>?
    @State private var hint = false
    @State private var player: AVAudioPlayer?
    @State private var playing = false
    @State private var playhead = 0.0
    @State private var playbackTask: Task<Void, Never>?
    private struct DraftKey: Hashable { let target: SendTarget; let group: GroupKey? }
    @MainActor private static var drafts: [DraftKey: String] = [:]
    private func draftKey(_ target: SendTarget) -> DraftKey { DraftKey(target: target, group: groupKey) }

    init(target: SendTarget?, placeholder: String = "Message…", note: String? = nil, autoFocus: Bool = false,
         reply: Binding<ReplyPreview?>, onSent: (() -> Void)? = nil,
         fieldId: String = "composer-field", sendId: String = "composer-send", groupKey: GroupKey? = nil,
         unavailableText: String = "Starting topic…") {
        self.groupKey = groupKey; self.unavailableText = unavailableText
        self.fieldId = fieldId; self.sendId = sendId
        self.target = target; self.placeholder = placeholder; self.note = note; self.autoFocus = autoFocus
        _reply = reply; self.onSent = onSent
    }
    private var showMic: Bool { reply?.answering == nil && !locked && segments.isEmpty && text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }
    private var recording: Bool { recorder?.isRecording == true }
    private var hasAudio: Bool { recording || starting || !segments.isEmpty }
    private var duration: Double { segments.reduce(0) { $0 + $1.duration } + (recorder?.finished.reduce(0) { $0 + $1.duration } ?? 0) + (recorder?.elapsed ?? 0) }

    var body: some View {
        VStack(spacing: 4) {
            if let error {
                HStack {
                    Text(error).themeFont(13).foregroundStyle(Theme.danger).accessibilityIdentifier("composer-error")
                    if micError && reply?.answering == nil { Button("Try again") { Task { await startRecording(lock: true) } }.themeFont(13, .semibold).frame(minHeight: 44).accessibilityIdentifier("composer-retry") }
                }
            }
            if let reply {
                HStack(spacing: 8) {
                    Rectangle().fill(Theme.brand).frame(width: 3)
                    VStack(alignment: .leading, spacing: 2) {
                        Text(reply.title).themeFont(13, .semibold).foregroundStyle(Theme.brand)
                        Text(reply.quote).themeFont(13).foregroundStyle(Theme.muted).lineLimit(1)
                    }
                    Spacer(minLength: 0)
                    control("xmark", "Cancel reply", "reply-close") { self.reply = nil }
                }.fixedSize(horizontal: false, vertical: true).padding(.horizontal, 12)
            }
            if hint { Text("Hold to record").themeFont(13).foregroundStyle(Theme.muted) }
            ZStack(alignment: .bottomTrailing) {
                if reply?.answering == nil && (hasAudio || busy && !segments.isEmpty) { recordingRow } else { composeRow }
                // Keep the gesture's view alive when the bar switches to recording.
                mic.opacity(showMic ? 1 : 0).allowsHitTesting(showMic)
                    .accessibilityHidden(!showMic)
                    .overlay(alignment: .top) {
                        if recording && !locked {
                            VStack(spacing: 8) { Image(systemName: "lock"); Image(systemName: "arrow.up") }
                                .themeFont(16).foregroundStyle(Theme.brand).frame(width: 44, height: 65)
                                .background(Theme.surface3, in: Capsule(style: .continuous)).offset(y: -77).accessibilityHidden(true)
                        }
                    }
            }
            if reply?.answering != nil, text.unicodeScalars.count > 1800 {
                Text("\(text.unicodeScalars.count)/2000").themeFont(13).foregroundStyle(Theme.muted)
            }
            if target == nil { Text(unavailableText).themeFont(13).foregroundStyle(Theme.muted) }
            else if let note, !hasAudio, reply?.answering == nil { Text(note).themeFont(13).foregroundStyle(Theme.muted).accessibilityIdentifier("composer-note") }
        }.padding(.horizontal, 8).padding(.vertical, 8)
            .frame(maxWidth: .infinity)
            .background(Theme.surface)
            .overlay(alignment: .top) { Rectangle().fill(Theme.border).frame(height: 0.5) }
            .accessibilityElement(children: .contain).accessibilityIdentifier("composer")
            .foregroundStyle(Theme.text).tint(Theme.brand)
            .sensoryFeedback(.success, trigger: success).sensoryFeedback(.warning, trigger: cancellation)
            .animation(reduceMotion ? nil : .easeOut(duration: 0.2), value: hasAudio)
            .task { text = target.flatMap { Self.drafts[draftKey($0)] } ?? ""; if autoFocus && target != nil { focused = true } }
            .onChange(of: reply?.answering?.id) { _, id in
                if id != nil {
                    if savedDraft == nil { savedDraft = text }
                    text = ""
                    holding = false; holdTask?.cancel(); hintTask?.cancel(); hint = false
                    if recording || starting { discard() }
                    attaching = false; focused = true
                } else {
                    restoreDraft()
                }
            }
            .onChange(of: text) { _, value in
                if reply?.answering == nil, savedDraft == nil, let target { Self.drafts[draftKey(target)] = value }
            }
            .onChange(of: target) { _, new in
                let draft = new.flatMap { Self.drafts[draftKey($0)] } ?? ""
                if reply?.answering != nil {
                    savedDraft = draft; reply = nil; restoreDraft()
                }
                text = draft; discard()
            }
            .onChange(of: model.answerTick) { _, _ in
                if let q = reply?.answering, !Self.isOpen(q, in: model) { endAnsweringClosed() }
            }
            // Answered on the dashboard or another phone: the question leaves the open list, answering mode ends.
            .onChange(of: model.questions.map(\.id)) { _, _ in
                if let q = reply?.answering, !Self.isOpen(q, in: model) { endAnsweringClosed() }
            }
            .onChange(of: recorder?.error) { _, value in if let value { error = value; micError = true; collect() } }
            .onDisappear { holding = false; holdTask?.cancel(); hintTask?.cancel(); discard() }
            .sheet(isPresented: $attaching) {
                MediaPicker { selection in Task { await sendMedia(selection) } }
                    .tint(Theme.brand)
            }
    }
    private var composeRow: some View {
        HStack(alignment: .bottom, spacing: 8) {
            control("plus", "Attach", "composer-attach") { focused = false; attaching = true }.disabled(target == nil || busy || reply?.answering != nil)
            TextField(target == nil ? unavailableText : placeholder, text: $text, axis: .vertical)
                .themeFont(17).lineLimit(1...5).padding(.horizontal, 12).padding(.vertical, 10)
                .background(Theme.surface, in: RoundedRectangle(cornerRadius: Theme.Radius.xl - 8, style: .continuous))
                .overlay(RoundedRectangle(cornerRadius: Theme.Radius.xl - 8, style: .continuous).stroke(Theme.borderStrong))
                .focused($focused).disabled(target == nil || busy).accessibilityIdentifier(fieldId)
            if text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { Color.clear.frame(width: 44, height: 44) }
            else { control("arrow.up", "Send message", sendId, filled: true) { Task { await sendText() } }.disabled(busy || target == nil) }
        }
    }
    private var mic: some View {
        Image(systemName: "mic").themeFont(20).foregroundStyle(Theme.onBrand).frame(width: 44, height: 44)
            .background(Theme.brand, in: Circle()).contentShape(Circle()).opacity(target == nil ? 0.4 : 1)
            .gesture(DragGesture(minimumDistance: 0).onChanged { value in
                guard target != nil, !busy else { return }
                if !holding {
                    holding = true; cancelledHold = false
                    holdTask = Task {
                        try? await Task.sleep(for: .milliseconds(250))
                        guard !Task.isCancelled, holding else { return }
                        await startRecording(lock: false)
                    }
                }
                if value.translation.width < -90 && !cancelledHold { cancelledHold = true; holdTask?.cancel(); discard(); cancellation += 1 }
                else if value.translation.height < -60, recording { locked = true }
            }.onEnded { _ in
                let wasRecording = recording
                holding = false; holdTask?.cancel()
                if locked || cancelledHold { return }
                if wasRecording { Task { await sendRecording() } }
                else if !starting {
                    hint = true; hintTask?.cancel()
                    hintTask = Task { try? await Task.sleep(for: .seconds(1)); if !Task.isCancelled { hint = false } }
                }
            })
            .accessibilityLabel("Record voice message").accessibilityAddTraits(.isButton)
            .accessibilityIdentifier("composer-mic")
            .accessibilityAction(named: "Record voice message") { toggleAccessibleRecording() }
            .accessibilityAction { toggleAccessibleRecording() }
    }
    private var recordingRow: some View {
        VStack(spacing: 4) {
            if busy { Text("Writing it down…").themeFont(13).foregroundStyle(Theme.muted) }
            let layout = typeSize.isAccessibilitySize ? AnyLayout(VStackLayout(spacing: 4)) : AnyLayout(HStackLayout(spacing: 4))
            layout {
                if locked || !recording { control("trash", "Discard recording", "rec-trash") { discard(); cancellation += 1 }.disabled(busy) }
                else { Circle().fill(Theme.danger).frame(width: 12, height: 12).accessibilityLabel("Recording") }
                Text(clock(duration)).themeFont(13).monospacedDigit()
                if recording {
                    waveform
                    if !locked { Text("‹ Slide to cancel").themeFont(13).foregroundStyle(Theme.muted) }
                } else if !segments.isEmpty {
                    control(playing ? "pause.fill" : "play.fill", playing ? "Pause preview" : "Play preview", "rec-play") { togglePlayback() }
                    Slider(value: $playhead, in: 0...max(segments.first?.duration ?? 0, 0.01), onEditingChanged: { _ in player?.currentTime = playhead })
                        .accessibilityLabel("Recording position").accessibilityIdentifier("rec-scrub")
                }
                if locked || !recording {
                    if recording { control("pause", "Pause recording", "rec-pause") { collect() } }
                    else { control("mic", "Resume recording", "rec-resume") { Task { await startRecording(lock: true) } }.disabled(busy) }
                    control("arrow.up", "Send recording", "rec-send", filled: true) { Task { await sendRecording() } }.disabled(busy || starting)
                } else {
                    Color.clear.frame(width: 44, height: 44)
                }
            }
        }.transition(.move(edge: .bottom).combined(with: .opacity))
            // The hold gesture is not reachable with VoiceOver / Switch Control: the recording row offers the same choices.
            .accessibilityAction(named: "Cancel recording") { discard(); cancellation += 1 }
            .accessibilityActions { if recording && !locked { Button("Lock recording") { locked = true } } }
    }
    private var waveform: some View {
        HStack(spacing: 3) {
            ForEach(Array((recorder?.levels ?? []).enumerated()), id: \.offset) { _, level in
                Capsule(style: .continuous).fill(Theme.muted).frame(width: 3, height: 4 + 22 * level)
            }
        }.frame(maxWidth: .infinity, minHeight: 28).animation(reduceMotion ? nil : .linear(duration: 0.08), value: recorder?.levels).accessibilityHidden(true)
    }
    private func control(_ symbol: String, _ label: String, _ id: String, filled: Bool = false, action: @escaping () -> Void) -> some View {
        Button(action: action) { Image(systemName: symbol).themeFont(20).frame(width: 44, height: 44)
            .foregroundStyle(filled ? Theme.onBrand : Theme.brand).background(filled ? Theme.brand : .clear, in: Circle()) }
            .buttonStyle(PressStyle()).accessibilityLabel(label).accessibilityIdentifier(id)
    }
    private func clock(_ seconds: Double) -> String { clockText(seconds) }
    private func dispatch(_ draft: MessageDraft, to target: SendTarget) async throws {
        if let groupKey { try await model.sendGroup(draft, key: groupKey) }
        else { try await model.send(draft, to: target) }
    }
    private func sendText() async {
        guard let target, !busy else { return }
        let trimmedText = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedText.isEmpty else { return }
        busy = true; error = nil; micError = false
        defer { busy = false }
        do {
            if let q = reply?.answering {
                // Closed meanwhile (answered here, elsewhere, or an option is being sent): keep what was typed, say why.
                if !Self.isOpen(q, in: model) || model.pendingAnswers[q.id] != nil {
                    endAnsweringClosed(sending: model.pendingAnswers[q.id] != nil); return
                }
                await model.answer(q, with: String(String.UnicodeScalarView(trimmedText.unicodeScalars.prefix(2000))))
                if model.answers[q.id] == nil && model.queuedAnswers[q.id] == nil {
                    error = "Your answer was not sent. Try again."
                    return
                }
                if reply?.answering?.id == q.id { reply = nil; restoreDraft() }
            } else {
                let sent = text
                let replyTo = reply?.messageId
                text = ""; Self.drafts[draftKey(target)] = nil; reply = nil
                do { try await dispatch(MessageDraft(text: sent, replyTo: replyTo), to: target) }
                catch {
                    // Never overwrite what was typed meanwhile.
                    if text.isEmpty { text = sent; Self.drafts[draftKey(target)] = sent }
                    throw error
                }
            }
            success += 1; onSent?()
        } catch { self.error = error.localizedDescription }
    }
    /// A free-text answer goes only to a question that is still open: listed by the relay and not answered on this phone.
    static func isOpen(_ q: Question, in model: AppModel) -> Bool {
        model.answers[q.id] == nil && model.questions.contains { $0.id == q.id }
    }
    /// The one way answering mode ends because the question closed (answered here, on the dashboard or another phone, or an
    /// option is being sent). Typed answer text is never dropped or silently re-targeted: with text, it stays in the field,
    /// the chip goes and the person is told why (the next Send is then a plain message they can see coming); without text
    /// the conversation draft comes back.
    private func endAnsweringClosed(sending: Bool = false) {
        if text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            reply = nil; restoreDraft()
        } else {
            savedDraft = nil; reply = nil
            error = sending ? "Your chosen answer is being sent." : "This question is already answered."
        }
    }
    private func restoreDraft() {
        guard let savedDraft else { return }
        text = savedDraft; self.savedDraft = nil
    }
    /// A photo, file or place from the "+" sheet: goes through the outbox like any message; the picker's temp files are removed after.
    private func sendMedia(_ selection: MediaSelection) async {
        defer { selection.cleanUp() }
        guard let target, reply?.answering == nil else { return }
        let draft: MessageDraft
        switch selection {
        case .files(let files, let caption): draft = MessageDraft(text: caption, files: files, replyTo: reply?.messageId)
        case .location(let place): draft = MessageDraft(location: place, replyTo: reply?.messageId)
        }
        do { try await dispatch(draft, to: target); reply = nil; success += 1; onSent?() }
        catch { self.error = error.localizedDescription; micError = false }
    }
    private func startRecording(lock: Bool) async {
        guard reply?.answering == nil, target != nil, !recording, !starting, !busy else { return }
        stopPlayback(); error = nil; micError = false; starting = true; locked = lock
        let generation = UUID(); recordingGeneration = generation
        let r = model.makeVoiceRecorder(); recorder = r
        do {
            try await r.start()
            if Task.isCancelled || recordingGeneration != generation || (!lock && !holding) { r.cancel(); if recordingGeneration == generation { recorder = nil } }
        } catch {
            self.error = r.error?.replacingOccurrences(of: "Settings to record.", with: "Settings to dictate.") ?? "Could not start the microphone."
            micError = true; r.cancel(); recorder = nil
        }
        starting = false
    }
    private func collect() {
        if let recorder { segments += recorder.stop(); self.recorder = nil }
        locked = true
    }
    private func sendRecording() async {
        guard reply?.answering == nil, let target, !busy else { return }
        collect()
        guard segments.reduce(0, { $0 + $1.duration }) >= 1 else {
            discard()   // too short to be a memo: say so instead of dropping it silently (the same hint as a plain tap)
            hint = true; hintTask?.cancel()
            hintTask = Task { try? await Task.sleep(for: .seconds(2)); if !Task.isCancelled { hint = false } }
            return
        }
        stopPlayback(); busy = true; error = nil; micError = false
        defer { busy = false }
        let replyId = reply?.messageId
        do {
            while let segment = segments.first {
                let draft = await model.voiceDraft(for: segment)
                try await dispatch(MessageDraft(voice: draft, replyTo: replyId), to: target)
                segments.removeFirst(); try? FileManager.default.removeItem(at: segment.url)
            }
            locked = false; reply = nil; success += 1; onSent?()
        } catch { self.error = error.localizedDescription }
    }
    private func discard() {
        guard !busy else { return }
        recordingGeneration = UUID()
        stopPlayback(); recorder?.cancel(); recorder = nil
        for segment in segments { try? FileManager.default.removeItem(at: segment.url) }
        segments = []; locked = false
    }
    private func toggleAccessibleRecording() {
        guard reply?.answering == nil, target != nil, !busy else { return }
        Task { if recording { await sendRecording() } else { await startRecording(lock: true) } }
    }
    private func stopPlayback() { playbackTask?.cancel(); player?.stop(); player = nil; playing = false; playhead = 0 }
    private func togglePlayback() {
        if playing { player?.pause(); playing = false; playbackTask?.cancel(); return }
        guard let first = segments.first else { return }
        do {
            if player == nil { AudioSession.playback(); player = try AVAudioPlayer(contentsOf: first.url) }
            if playhead >= first.duration { playhead = 0 }
            player?.currentTime = playhead; playing = player?.play() == true
            playbackTask = Task {
                while !Task.isCancelled, playing {
                    try? await Task.sleep(for: .milliseconds(100))
                    guard !Task.isCancelled else { return }
                    playhead = player?.currentTime ?? 0; playing = player?.isPlaying == true
                }
            }
        } catch { self.error = "Could not play the recording." }
    }
}
