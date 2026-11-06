import SwiftUI

struct MiniPlayer: View {
    @Environment(AppModel.self) private var model
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        Group {
            if model.speech.isActive {
                HStack(spacing: 7) {
                    Button {
                        NotePlayer.current?.stop()
                        model.speech.toggle()
                    } label: {
                        Group {
                            if case .loading = model.speech.state { ProgressView().tint(Theme.brand) }
                            else { Image(systemName: isPlaying ? "pause.fill" : "play.fill") }
                        }.frame(width: 44, height: 44)
                    }.disabled(isLoading).accessibilityIdentifier("mini-toggle")
                        .accessibilityLabel(isPlaying ? "Pause voice message" : "Play voice message")
                    Text((model.speech.current?.title ?? "") + " · Voice memo")
                        .themeFont(13, .semibold).frame(maxWidth: .infinity, alignment: .leading)
                    Button { model.speech.cycleRate() } label: {
                        Text(voiceRateText(model.speech.rate)).themeFont(13)
                            .frame(minWidth: 44, minHeight: 44)
                    }.accessibilityLabel("Playback speed").accessibilityValue(voiceRateText(model.speech.rate))
                        .accessibilityIdentifier("mini-speed")
                    Button { model.speech.stop() } label: {
                        Image(systemName: "xmark").frame(width: 44, height: 44)
                    }.accessibilityLabel("Close voice player").accessibilityIdentifier("mini-close")
                }.themeFont(15).foregroundStyle(Theme.brand).buttonStyle(PressStyle())
                    .padding(.horizontal, 12).frame(minHeight: 44)
                    .background(Theme.brand.opacity(0.14))
                    .accessibilityElement(children: .contain).accessibilityIdentifier("mini-player")
                    .transition(reduceMotion ? .identity : .move(edge: .top))
            }
        }.animation(reduceMotion ? nil : .easeOut(duration: 0.2), value: model.speech.isActive)
    }

    private var isPlaying: Bool { if case .playing = model.speech.state { true } else { false } }
    private var isLoading: Bool { if case .loading = model.speech.state { true } else { false } }
}
