import SwiftUI
import AVFoundation
import MediaPlayer
import Observation

struct Waveform: View {
    var levels: [Double]
    var progress: Double? = nil
    var tint: Color = Theme.borderStrong

    init(levels: [Double], progress: Double? = nil, tint: Color = Theme.borderStrong) {
        self.levels = levels; self.progress = progress; self.tint = tint
    }

    init(seed: String, progress: Double? = nil, tint: Color = Theme.borderStrong) {
        var state = seed.utf8.reduce(UInt64(5381)) { ($0 &* 33) &+ UInt64($1) }
        self.levels = (0..<28).map { _ in
            state = state &* 6364136223846793005 &+ 1442695040888963407
            return 0.15 + Double((state >> 32) % 86) / 100
        }
        self.progress = progress; self.tint = tint
    }

    var body: some View {
        GeometryReader { proxy in
            HStack(spacing: max(1, (proxy.size.width - 84) / 27)) {
                ForEach(0..<28, id: \.self) { index in
                    let level = levels.isEmpty ? 0.2 : levels[min(levels.count - 1, index * levels.count / 28)]
                    RoundedRectangle(cornerRadius: 3)
                        .fill(Double(index) / 28 < (progress ?? 0) ? Theme.brand : tint)
                        .frame(width: min(3, proxy.size.width / 55), height: max(4, 28 * min(1, max(0, level))))
                }
            }.frame(width: proxy.size.width, height: proxy.size.height)
        }.frame(height: 32).accessibilityHidden(true)
    }
}

@MainActor @Observable final class NotePlayer {
    static weak var current: NotePlayer?
    private(set) var isPlaying = false
    private(set) var progress: Double = 0
    private(set) var rate: Double = 1
    private(set) var duration: Double = 0
    private(set) var isAvailable = false
    @ObservationIgnored private var audio: AVAudioPlayer?
    @ObservationIgnored private var loop: Task<Void, Never>?

    init(data: Data? = nil) { if let data { load(data) } }

    func load(_ data: Data) {
        stop()
        audio = try? AVAudioPlayer(data: data)
        audio?.enableRate = true
        audio?.prepareToPlay()
        duration = audio?.duration ?? 0
        isAvailable = audio != nil
    }

    func play(model: AppModel) {
        guard let audio else { return }
        Self.current?.pause()
        if Self.current !== self { Self.current?.stop() }
        Self.current = self
        model.speech.stop()
        AudioSession.playback()
        if progress >= 1 { audio.currentTime = 0; progress = 0 }
        audio.rate = Float(rate)
        isPlaying = audio.play()
        guard isPlaying else { return }
        loop?.cancel()
        loop = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(for: .milliseconds(100))
                guard !Task.isCancelled, let self, let audio = self.audio else { return }
                self.progress = audio.duration > 0 ? min(1, audio.currentTime / audio.duration) : 0
                if !audio.isPlaying {
                    self.progress = 1; self.isPlaying = false
                    if Self.current === self { Self.current = nil }
                    return
                }
            }
        }
    }

    func pause() { audio?.pause(); isPlaying = false; loop?.cancel(); loop = nil }
    func stop() {
        pause(); audio?.stop(); audio?.currentTime = 0; progress = 0
        if Self.current === self { Self.current = nil }
    }
    func cycleRate() { rate = rate == 1 ? 1.5 : (rate == 1.5 ? 2 : 1); audio?.rate = Float(rate) }
    func seek(to fraction: Double) {
        guard let audio, fraction.isFinite else { return }
        progress = min(1, max(0, fraction)); audio.currentTime = progress * audio.duration
    }
}

func voiceRateText(_ rate: Double) -> String { rate == 1.5 ? "1.5x" : "\(Int(rate))x" }
private func voiceDurationText(_ duration: Double) -> String {
    let seconds = duration.isFinite ? max(0, Int(duration)) : 0
    return String(format: "%d:%02d", seconds / 60, seconds % 60)
}

struct OwnVoiceBubble: View {
    let item: ConvItem
    let conversationLanguage: String
    let onRetry: () -> Void
    let onDiscard: () -> Void
    @Environment(AppModel.self) private var model
    @State private var player = NotePlayer()

    private var duration: Double {
        item.attachments.first(where: { $0.kind == .voice })?.duration
            ?? item.queuedFiles.first(where: { $0.kind == .voice })?.duration ?? player.duration
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 8) {
                Button {
                    if player.isPlaying { player.pause() } else { player.play(model: model) }
                } label: {
                    Image(systemName: player.isPlaying ? "pause.fill" : "play")
                        .themeFont(16).frame(width: 44, height: 44)
                        .foregroundStyle(Theme.onBrand).background(Theme.brand, in: Circle())
                }.disabled(!player.isAvailable).opacity(player.isAvailable ? 1 : 0.45)
                    .accessibilityIdentifier("voice-play")
                    .accessibilityLabel(player.isAvailable ? "Play voice message, \(voiceDurationText(duration))" : "Audio not available")
                    .accessibilityValue(player.isPlaying ? "Pause" : "Play")
                scrubber
                Button { player.cycleRate() } label: {
                    Text(voiceRateText(player.rate)).themeFont(13)
                        .frame(width: 44, height: 44).background(Theme.surface3, in: RoundedRectangle(cornerRadius: 12))
                }.accessibilityIdentifier("voice-speed").accessibilityLabel("Playback speed")
                    .accessibilityValue(voiceRateText(player.rate))
            }
            HStack(spacing: 5) {
                Text(voiceDurationText(duration)).foregroundStyle(Theme.muted)
                Circle().fill(Theme.brand).frame(width: 10, height: 10).accessibilityHidden(true)
                Text("Voice memo").foregroundStyle(Theme.brand)
            }.themeFont(13).padding(.leading, 48)
            Text(item.voice?.transcript ?? item.text).themeFont(17).textSelection(.enabled)
                .accessibilityIdentifier("voice-transcript")
            ViewThatFits(in: .horizontal) {
                HStack(alignment: .bottom, spacing: 5) { language; receipt }
                VStack(alignment: .trailing, spacing: 4) { language; receipt }
            }
        }.foregroundStyle(Theme.text).buttonStyle(PressStyle())
            .padding(.vertical, 11).padding(.horizontal, 13)
            .background(Theme.brand.opacity(0.14), in: RoundedRectangle(cornerRadius: 17))
            .overlay(RoundedRectangle(cornerRadius: 17).stroke(Theme.brand.opacity(0.3)))
            .containerRelativeFrame(.horizontal) { width, _ in width * 0.8 }
            .frame(maxWidth: .infinity, alignment: .trailing)
            .task(id: item.voice?.blobId) { await loadAudio() }
            .onDisappear { player.stop() }
    }

    @ViewBuilder private var language: some View {
        if let voice = item.voice, let label = LanguageLabel.label(memo: voice.lang, conversation: conversationLanguage) {
            Text(label).themeFont(13).foregroundStyle(Theme.muted)
        }
    }
    private var receipt: some View {
        ReceiptView(receipt: item.receipt ?? .sent, time: ChatBuilder.timeText(item.at), onRetry: onRetry, onDiscard: onDiscard)
    }
    private var scrubber: some View {
        GeometryReader { proxy in
            Waveform(seed: item.id, progress: player.progress).frame(height: 44)
                .contentShape(Rectangle())
                .gesture(DragGesture(minimumDistance: 0).onChanged { value in
                    player.seek(to: value.location.x / max(1, proxy.size.width))
                })
        }.frame(height: 44).accessibilityElement(children: .ignore)
            .accessibilityLabel("Voice message position").accessibilityValue("\(Int(player.progress * 100)) percent")
            .accessibilityIdentifier("voice-seek")
            .accessibilityAdjustableAction { direction in
                player.seek(to: player.progress + (direction == .increment ? 0.1 : -0.1))
            }.allowsHitTesting(player.isAvailable)
    }
    private func loadAudio() async {
        if let queued = model.outbox.item(clientId: item.clientId ?? ""),
           let file = queued.voice?.file ?? item.queuedFiles.first(where: { $0.kind == .voice }),
           let data = try? Data(contentsOf: model.outbox.fileURL(queued, file)) {
            player.load(data); return
        }
        let blob = item.voice?.blobId ?? item.attachments.first(where: { $0.kind == .voice })?.blobId
        if let blob, !blob.isEmpty, let data = await model.blob(blob), !Task.isCancelled { player.load(data) }
    }
}

struct AgentMemoBubble: View {
    let item: ConvItem
    let conversationId: ConversationID
    let workspaceName: String
    @Environment(AppModel.self) private var model
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var showText = false
    @State private var timingDate = Date()
    @State private var elapsed: Double = 0
    @State private var duration: Double = 0
    private var current: Bool { model.speech.current?.messageId == item.id }
    private var playing: Bool { model.speech.state == .playing(item.id) }
    private var listened: Bool { model.speech.isListened(item.id) }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            VStack(alignment: .leading, spacing: 8) {
                HStack(spacing: 8) {
                    Button(action: toggle) {
                        Group {
                            if model.speech.state == .loading(item.id) { ProgressView().tint(Theme.onBrand) }
                            else { Image(systemName: playing ? "pause.fill" : "play") }
                        }.themeFont(16).frame(width: 44, height: 44)
                            .foregroundStyle(listened ? Theme.brand : Theme.onBrand)
                            .background(listened ? Theme.surface3 : Theme.brand, in: Circle())
                    }.disabled(!item.canPlay || model.speech.state == .loading(item.id))
                        .accessibilityIdentifier("voice-play")
                        .accessibilityLabel("Play voice message" + (duration > 0 ? ", \(voiceDurationText(duration))" : ""))
                        .accessibilityValue(playing ? "Pause" : "Play").accessibilityHint(workspaceName)
                    GeometryReader { proxy in
                        Waveform(seed: item.id, progress: current ? model.speech.progress : 0).frame(height: 44)
                            .contentShape(Rectangle())
                            .gesture(DragGesture(minimumDistance: 0).onChanged { value in
                                if current { model.speech.seek(to: value.location.x / max(1, proxy.size.width)) }
                            })
                    }.frame(height: 44).accessibilityIdentifier("voice-scrub")
                    Button { model.speech.cycleRate() } label: {
                        Text(voiceRateText(model.speech.rate)).themeFont(13).frame(width: 44, height: 44)
                            .background(Theme.surface3, in: RoundedRectangle(cornerRadius: 12))
                    }.accessibilityIdentifier("voice-speed").accessibilityLabel("Playback speed")
                        .accessibilityValue(voiceRateText(model.speech.rate))
                }
                HStack(spacing: 5) {
                    if duration > 0 { Text(voiceDurationText(duration)).foregroundStyle(Theme.muted) }
                    Circle().fill(listened ? Theme.muted : Theme.brand).frame(width: 10, height: 10).accessibilityHidden(true)
                    Text(listened ? "Listened" : "Voice memo").foregroundStyle(listened ? Theme.muted : Theme.brand)
                }.themeFont(13).padding(.leading, 48)
                Button {
                    withAnimation(reduceMotion ? nil : .easeOut(duration: 0.2)) { showText.toggle() }
                } label: {
                    Text(showText ? "Hide text" : "Show text").themeFont(13).foregroundStyle(Theme.muted)
                        .frame(minHeight: 44).contentShape(Rectangle())
                }.accessibilityIdentifier("memo-show-text")
                    .accessibilityValue(showText ? "Expanded" : "Collapsed")
                if showText {
                    Text(item.text).themeFont(17).textSelection(.enabled).accessibilityIdentifier("voice-transcript")
                }
                Text(ChatBuilder.timeText(item.at)).themeFont(13).foregroundStyle(Theme.muted)
                    .frame(maxWidth: .infinity, alignment: .trailing)
            }.padding(.vertical, 11).padding(.horizontal, 13)
                .background(Theme.surface2, in: RoundedRectangle(cornerRadius: 17))
            if current, let notice = model.speech.notice {
                Text(notice).themeFont(13).foregroundStyle(Theme.muted)
            }
        }.foregroundStyle(Theme.text).buttonStyle(PressStyle())
            .containerRelativeFrame(.horizontal) { width, _ in width * 0.88 }
            .frame(maxWidth: .infinity, alignment: .leading)
            .onChange(of: model.speech.state, initial: true) { _, _ in captureTiming() }
            .onChange(of: model.speech.rate) { _, _ in captureTiming() }
    }

    private func toggle() {
        NotePlayer.current?.stop()
        switch model.speech.state {
        case .playing(let id) where id == item.id: model.speech.pause()
        case .paused(let id) where id == item.id: model.speech.resume()
        default: model.play(item, in: conversationId)
        }
    }
    // SpeechPlayer publishes timing for recorded audio through its existing system controls.
    // Synthesized speech has no duration; leave its waveform indeterminate.
    private func captureTiming() {
        guard current, !model.speech.usingPhoneVoice else { elapsed = 0; duration = 0; return }
        let info = MPNowPlayingInfoCenter.default().nowPlayingInfo ?? [:]
        elapsed = (info[MPNowPlayingInfoPropertyElapsedPlaybackTime] as? NSNumber)?.doubleValue ?? 0
        duration = (info[MPMediaItemPropertyPlaybackDuration] as? NSNumber)?.doubleValue ?? 0
        timingDate = Date()
    }
    private func progress(at date: Date) -> Double? {
        guard current, duration > 0 else { return listened ? 1 : nil }
        return min(1, max(0, (elapsed + (playing ? date.timeIntervalSince(timingDate) * model.speech.rate : 0)) / duration))
    }
}
