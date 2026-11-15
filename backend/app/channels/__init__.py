"""Canali di interazione: adattatori davanti al turno dell'agente (design: docs/channels/CHANNELS_DESIGN.md).

Un canale trasforma un messaggio in arrivo in un turno su una conversazione e consegna la risposta; l'`ChannelHub`
li avvia con l'applicazione e applica la regola di sensibilità a ogni messaggio che esce verso un canale."""
