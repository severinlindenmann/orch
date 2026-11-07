import SwiftUI
import AVFoundation

enum AttachKind: String, CaseIterable { case camera, scan, photos, files, location
    var title: String { switch self { case .camera: "Camera"; case .scan: "Scan document"; case .photos: "Photos"; case .files: "Files"; case .location: "Location" } }
    var symbol: String { switch self { case .camera: "camera"; case .scan: "doc.viewfinder"; case .photos: "photo"; case .files: "doc"; case .location: "mappin.and.ellipse" } }
}
struct ComposerHooks {
    var attach: (AttachKind, _ send: @escaping (MessageDraft) async -> Void) -> Void = { _, _ in }
    static var none: ComposerHooks { ComposerHooks() }
}
struct ReplyPreview: Equatable { let messageId: String; let title: String; let quote: String }

struct Composer: View {
    let target: SendTarget?
    var placeholder: String
    var note: String?
    var autoFocus: Bool
    @Binding var reply: ReplyPreview?
    var hooks: ComposerHooks
    var onSent: (() -> Void)?
    /// Accessibility ids of the text field and send button (the New topic screen keeps its older ids).
    var fieldId = "composer-field"
    var sendId = "composer-send"
    @Environment(AppModel.self) private var model
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.dynamicTypeSize) private var typeSize
    @FocusState private var focused: Bool
    @State private var text = ""
    @State private var error: String?
    @State private var micError = false
    @State private var attaching = false
    @State private var attachment: AttachKind?
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
    @MainActor private static var drafts: [SendTarget: String] = [:]

    init(target: SendTarget?, placeholder: String = "Message…", note: String? = nil, autoFocus: Bool = false,
         reply: Binding<ReplyPreview?>, hooks: ComposerHooks = .none, onSent: (() -> Void)? = nil,
         fieldId: String = "composer-field", sendId: String = "composer-send") {
        self.fieldId = fieldId; self.sendId = sendId
        self.target = target; self.placeholder = placeholder; self.note = note; self.autoFocus = autoFocus
        _reply = reply; self.hooks = hooks; self.onSent = onSent
    }
    private var showMic: Bool { !locked && segments.isEmpty && text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }
    private var recording: Bool { recorder?.isRecording == true }
    private var hasAudio: Bool { recording || starting || !segments.isEmpty }
    private var duration: Double { segments.reduce(0) { $0 + $1.duration } + (recorder?.finished.reduce(0) { $0 + $1.duration } ?? 0) + (recorder?.elapsed ?? 0) }

    var body: some View {
        VStack(spacing: 4) {
            if let error {
                HStack {
                    Text(error).themeFont(13).foregroundStyle(Theme.danger).accessibilityIdentifier("composer-error")
                    if micError { Button("Try again") { Task { await startRecording(lock: true) } }.themeFont(13, .semibold).frame(minHeight: 44).accessibilityIdentifier("composer-retry") }
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
                if hasAudio || busy && !segments.isEmpty { recordingRow } else { composeRow }
                // Keep the gesture's view alive when the bar switches to recording.
                mic.opacity(showMic ? 1 : 0).allowsHitTesting(showMic)
                    .accessibilityHidden(!showMic)
                    .overlay(alignment: .top) {
                        if recording && !locked {
                            VStack(spacing: 8) { Image(systemName: "lock"); Image(systemName: "arrow.up") }
                                .themeFont(16).foregroundStyle(Theme.brand).frame(width: 44, height: 65)
                                .background(Theme.surface3, in: Capsule()).offset(y: -77).accessibilityHidden(true)
                        }
                    }
            }
            if target == nil { Text("Starting topic…").themeFont(13).foregroundStyle(Theme.muted) }
            else if let note, !hasAudio { Text(note).themeFont(13).foregroundStyle(Theme.muted).accessibilityIdentifier("composer-note") }
        }.padding(.horizontal, 12).padding(.vertical, 8).background(Theme.surface)
            .accessibilityElement(children: .contain).accessibilityIdentifier("composer")
            .foregroundStyle(Theme.text).tint(Theme.brand)
            .sensoryFeedback(.success, trigger: success).sensoryFeedback(.warning, trigger: cancellation)
            .animation(reduceMotion ? nil : .easeOut(duration: 0.2), value: hasAudio)
            .task { text = target.flatMap { Self.drafts[$0] } ?? ""; if autoFocus && target != nil { focused = true } }
            .onChange(of: text) { _, value in if let target { Self.drafts[target] = value } }
            .onChange(of: target) { _, new in text = new.flatMap { Self.drafts[$0] } ?? ""; discard() }
            .onChange(of: recorder?.error) { _, value in if let value { error = value; micError = true; collect() } }
            .onDisappear { holding = false; holdTask?.cancel(); hintTask?.cancel(); discard() }
            .sheet(isPresented: $attaching, onDismiss: {
                if let kind = attachment { attachment = nil; hooks.attach(kind, sendDraft) }
            }) {
                ScrollView {
                    LazyVGrid(columns: [GridItem(.adaptive(minimum: 90))], spacing: 18) {
                        ForEach(AttachKind.allCases, id: \.self) { kind in
                            Button { attachment = kind; attaching = false } label: {
                                VStack(spacing: 8) {
                                    Image(systemName: kind.symbol).themeFont(22).frame(width: 53, height: 53).background(Theme.surface3, in: RoundedRectangle(cornerRadius: 17))
                                    Text(kind.title).themeFont(13)
                                }.frame(maxWidth: .infinity, minHeight: 80)
                            }.buttonStyle(PressStyle()).accessibilityIdentifier("attach-\(kind.rawValue)")
                        }
                    }.padding(24)
                }.presentationDetents([.height(300), .large]).presentationDragIndicator(.visible).presentationBackground(Theme.surface).tint(Theme.brand)
            }
    }
    private var composeRow: some View {
        HStack(alignment: .bottom, spacing: 8) {
            control("plus", "Attach", "composer-attach") { attaching = true }.disabled(target == nil || busy)
            TextField(target == nil ? "Starting topic…" : placeholder, text: $text, axis: .vertical)
                .themeFont(17).lineLimit(1...5).padding(.horizontal, 12).padding(.vertical, 10)
                .background(Theme.surface, in: RoundedRectangle(cornerRadius: 24))
                .overlay(RoundedRectangle(cornerRadius: 24).stroke(Theme.borderStrong))
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
                Capsule().fill(Theme.muted).frame(width: 3, height: 4 + 22 * level)
            }
        }.frame(maxWidth: .infinity, minHeight: 28).animation(reduceMotion ? nil : .linear(duration: 0.08), value: recorder?.levels).accessibilityHidden(true)
    }
    private func control(_ symbol: String, _ label: String, _ id: String, filled: Bool = false, action: @escaping () -> Void) -> some View {
        Button(action: action) { Image(systemName: symbol).themeFont(20).frame(width: 44, height: 44)
            .foregroundStyle(filled ? Theme.onBrand : Theme.brand).background(filled ? Theme.brand : .clear, in: Circle()) }
            .buttonStyle(PressStyle()).accessibilityLabel(label).accessibilityIdentifier(id)
    }
    private func clock(_ seconds: Double) -> String { clockText(seconds) }
    private func sendText() async {
        guard let target, !busy else { return }
        busy = true; error = nil; micError = false
        defer { busy = false }
        do {
            try await model.send(MessageDraft(text: text, replyTo: reply?.messageId), to: target)
            text = ""; Self.drafts[target] = nil; reply = nil; success += 1; onSent?()
        } catch { self.error = error.localizedDescription }
    }
    private func sendDraft(_ draft: MessageDraft) async {
        guard let target else { return }
        var draft = draft; if draft.replyTo == nil { draft.replyTo = reply?.messageId }
        do { try await model.send(draft, to: target); reply = nil; success += 1; onSent?() }
        catch { self.error = error.localizedDescription; micError = false }
    }
    private func startRecording(lock: Bool) async {
        guard target != nil, !recording, !starting, !busy else { return }
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
        guard let target, !busy else { return }
        collect()
        guard segments.reduce(0, { $0 + $1.duration }) >= 1 else { discard(); return }
        stopPlayback(); busy = true; error = nil; micError = false
        defer { busy = false }
        let replyId = reply?.messageId
        do {
            while let segment = segments.first {
                let draft = await model.voiceDraft(for: segment)
                try await model.send(MessageDraft(voice: draft, replyTo: replyId), to: target)
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
        guard target != nil, !busy else { return }
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
