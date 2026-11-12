import SwiftUI

struct MuteChoices: View {
    let select: (Mute) -> Void
    var body: some View {
        ForEach(MuteChoice.allCases) { choice in
            Button(choice.rawValue) { select(choice.mute()) }
        }
    }
}

struct MuteMenu: View {
    let muted: Bool
    let select: (Mute) -> Void
    var body: some View {
        if muted { Button("Unmute", systemImage: "bell") { select(.off) } }
        else { Menu("Mute", systemImage: "bell.slash") { MuteChoices(select: select) } }
    }
}

struct ChatMuteButton: View {
    let name: String
    let muted: Bool
    var groupStyle = false
    let select: (Mute) -> Void
    @State private var choosing = false
    var body: some View {
        Button {
            if muted { select(.off) } else { choosing = true }
        } label: {
            Image(systemName: muted ? "bell.slash" : "bell").themeFont(20).foregroundStyle(Theme.text)
                .frame(width: 44, height: 44).background(groupStyle ? Theme.surface2 : Theme.surface3, in: Circle())
        }.buttonStyle(PressStyle()).accessibilityLabel(muted ? "Unmute" : "Mute").accessibilityIdentifier("chat-mute")
            .confirmationDialog("Mute \(name)", isPresented: $choosing, titleVisibility: .visible) {
                MuteChoices(select: select)
                Button("Cancel", role: .cancel) {}
            }
    }
}

struct MutedIcon: View {
    var body: some View {
        Image(systemName: "bell.slash").themeFont(13).foregroundStyle(Theme.muted).accessibilityLabel("Muted")
    }
}

struct MuteAllSettings: View {
    @Environment(AppModel.self) private var model
    @State private var choosing = false
    var body: some View {
        TimelineView(.everyMinute) { context in
            VStack(alignment: .leading, spacing: 6) {
                Toggle("Mute all", isOn: Binding(get: { model.isMutedAll(now: context.date) }, set: { on in
                    if on { choosing = true } else { Task { await model.muteAll(.off) } }
                })).themeFont(17).tint(Theme.brand).accessibilityIdentifier("mute-all")
                Text("Silences notifications inside the app").themeFont(13).foregroundStyle(Theme.muted)
                if model.isMutedAll(now: context.date) {
                    Text(MuteRules.endLabel(model.settings.muteAllUntil)).themeFont(13).foregroundStyle(Theme.muted)
                }
            }.padding(16)
        }.confirmationDialog("Mute all", isPresented: $choosing, titleVisibility: .visible) {
            MuteChoices { mute in Task { await model.muteAll(mute) } }
            Button("Cancel", role: .cancel) {}
        }
    }
}

struct MuteAllBanner: View {
    @Environment(AppModel.self) private var model
    var body: some View {
        TimelineView(.everyMinute) { context in
            if model.isMutedAll(now: context.date) {
                HStack(spacing: 8) {
                    Image(systemName: "bell.slash").foregroundStyle(Theme.muted).accessibilityHidden(true)
                    Text("Notifications off · " + MuteRules.endLabel(model.settings.muteAllUntil, banner: true))
                        .lineLimit(1).minimumScaleFactor(0.7)
                    Spacer(minLength: 0)
                    Button("Turn on") { Task { await model.muteAll(.off) } }
                        .foregroundStyle(Theme.brand).frame(minHeight: 44).buttonStyle(PressStyle())
                        .accessibilityIdentifier("mute-all-off")
                }.themeFont(13).padding(.horizontal, 12).padding(.vertical, 4)
                    .background(Theme.surface2, in: RoundedRectangle(cornerRadius: Theme.Radius.m))
                    .accessibilityElement(children: .contain).accessibilityIdentifier("mute-all-banner")
            }
        }
    }
}
