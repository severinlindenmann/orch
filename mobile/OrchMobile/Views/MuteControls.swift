import SwiftUI
import UserNotifications

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
            let muted = model.isMutedAll(now: context.date)
            VStack(alignment: .leading, spacing: 6) {
                Toggle("Mute all", isOn: Binding(get: { muted }, set: { on in
                    if on { choosing = true } else { Task { await model.muteAll(.off) } }
                })).themeFont(17).tint(Theme.brand).accessibilityIdentifier("mute-all")
                Text(muted ? MuteRules.mutedText(model.settings.muteAllUntil, now: context.date)
                           : "You get a notification for questions and finished work.")
                    .themeFont(13).foregroundStyle(Theme.muted)
                NotificationDeniedNote()
            }.padding(16)
        }.confirmationDialog("Mute all", isPresented: $choosing, titleVisibility: .visible) {
            MuteChoices { mute in Task { await model.muteAll(mute) } }
            Button("Cancel", role: .cancel) {}
        }
    }
}

/// Yellow note shown only while iPhone Settings has notifications off for orch.
struct NotificationDeniedNote: View {
    @State private var access: NotificationAccess = .allowed
    @Environment(\.scenePhase) private var scenePhase
    var body: some View {
        Group {
            if access == .denied {
                VStack(alignment: .leading, spacing: 4) {
                    Text("Notifications are off in iPhone Settings.").themeFont(15, .semibold)
                    Text("orch can't tell you about questions.").themeFont(13)
                    Button("Open iPhone Settings") {
                        if let url = URL(string: UIApplication.openSettingsURLString) { UIApplication.shared.open(url) }
                    }.themeFont(15, .semibold).foregroundStyle(Theme.brand).frame(minHeight: 44).accessibilityIdentifier("open-ios-settings")
                }.frame(maxWidth: .infinity, alignment: .leading).padding(12)
                    .background(Theme.warn.opacity(0.18), in: RoundedRectangle(cornerRadius: Theme.Radius.m))
                    .accessibilityElement(children: .contain).accessibilityIdentifier("notifications-denied-note")
            }
        }
        .task { await read() }
        .onChange(of: scenePhase) { _, phase in if phase == .active { Task { await read() } } }
    }
    private func read() async {
        access = NotificationAccess.from(await UNUserNotificationCenter.current().notificationSettings().authorizationStatus)
    }
}

/// Top of the Chats list: the yellow permission note when iPhone blocks notifications, else the mute-all banner (never both).
struct NotificationBanner: View {
    @State private var denied = false
    @Environment(\.scenePhase) private var scenePhase
    var body: some View {
        Group {
            if denied { NotificationDeniedNote() } else { MuteAllBanner() }
        }
        .task { await read() }
        .onChange(of: scenePhase) { _, phase in if phase == .active { Task { await read() } } }
    }
    private func read() async {
        denied = NotificationAccess.from(await UNUserNotificationCenter.current().notificationSettings().authorizationStatus) == .denied
    }
}

struct MuteAllBanner: View {
    @Environment(AppModel.self) private var model
    var body: some View {
        TimelineView(.everyMinute) { context in
            if model.isMutedAll(now: context.date) {
                HStack(spacing: 8) {
                    Image(systemName: "bell.slash").foregroundStyle(Theme.muted).accessibilityHidden(true)
                    Text(MuteRules.mutedText(model.settings.muteAllUntil, now: context.date))
                        .lineLimit(1).minimumScaleFactor(0.7)
                    Spacer(minLength: 0)
                    Button("Unmute") { Task { await model.muteAll(.off) } }
                        .foregroundStyle(Theme.brand).frame(minHeight: 44).buttonStyle(PressStyle())
                        .accessibilityIdentifier("mute-all-off")
                }.themeFont(13).padding(.horizontal, 12).padding(.vertical, 4)
                    .background(Theme.surface2, in: RoundedRectangle(cornerRadius: Theme.Radius.m))
                    .accessibilityElement(children: .contain).accessibilityIdentifier("mute-all-banner")
            }
        }
    }
}
